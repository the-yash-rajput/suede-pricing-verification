"""Assert-based checks of the shared rules on RECORDED evidence (fixtures/carson-sofa.recorded.js, saved
2026-11-10). Not a live observation. No network, no DB.  Run: python test_validate.py"""
import json
from decimal import Decimal
from pathlib import Path

from pricecheck.brands.shopify import observe_json, pick_variant, valid_options
from pricecheck.core import Observation, Request, validate

P = json.loads((Path(__file__).parent / "fixtures/carson-sofa.recorded.js").read_text())
URL = "https://www.luluandgeorgia.com/products/carson-sofa"
T = "2026-11-10T16:39:00Z"


def run(variant, **obs_overrides):
    req = Request("Lulu and Georgia", URL, variant)
    obs = observe_json(req, P, URL + ".js")
    obs.currency, obs.market = obs_overrides.pop("currency", "USD"), obs_overrides.pop("market", "US")
    for k, v in obs_overrides.items():
        setattr(obs, k, v)
    return validate(req, obs, "r-test", T)


# 1. exact variant -> right id + price; same fabric, different sizes -> different prices
r = run({"Color": "Ivory Modern Boucle", "Size": '103"W'})
assert r["outcome"]["status"] == "resolved", r["outcome"]
assert r["requested_variant"]["resolved_variant_id"] == "42487540056163"
assert r["current_amount"] == "2598.00"
assert run({"Color": "Ivory Modern Boucle", "Size": '85"W'})["current_amount"] != "2598.00"
assert list(r)[:11] == ["brand", "product", "requested_variant", "market", "currency", "current_amount",
                        "price_basis", "source", "observation_time", "outcome", "supporting_evidence"]

# 2. compare_at == price -> not a sale, no compare-at reported
assert r["price_basis"] == {"type": "current_selling", "compare_at_amount": None, "on_sale": False, "conditions": []}

# 3. invalid size -> unresolved, valid options listed, NO default substitution
bad = run({"Color": "Ivory Modern Boucle", "Size": '200"W'})
assert bad["outcome"]["status"] == "unresolved" and bad["outcome"]["reason"] == "variant_not_found"
assert bad["current_amount"] is None and bad["requested_variant"]["resolved_variant_id"] is None
assert '103"W' in bad["outcome"]["detail"]["valid_options"]["Size"]

# 4. partial request (only Size) is ambiguous -> no pick
assert pick_variant(P, {"Size": '103"W'}) is None
assert len(valid_options(P)["Color"]) == 25

# 5. real sale: compare_at > price -> on_sale with compare-at
sale = run({"Color": "Ivory Modern Boucle", "Size": '103"W'}, amount=Decimal("2198.00"), compare_at=Decimal("2598.00"))
assert sale["current_amount"] == "2198.00" and sale["price_basis"]["compare_at_amount"] == "2598.00"
assert sale["price_basis"]["on_sale"] is True

# 6. wrong market / currency -> unresolved, never a converted guess
assert run({"Color": "Ivory Modern Boucle", "Size": '103"W'}, currency="INR")["outcome"]["reason"] == "wrong_market"

# 7. page disagrees with JSON -> unresolved
dis = run({"Color": "Ivory Modern Boucle", "Size": '103"W'},
          cross_check={"method": "browser_dom", "amount": Decimal("2398.00")})
assert dis["outcome"]["reason"] == "sources_disagree" and dis["current_amount"] is None

# 8. range-only and conditional-only prices are never resolved
req = Request("Serena & Lily", "https://x", {"Size": "King/Cal King", "Color": "Grove"})
base = dict(selected_options={"Size": "King/Cal King", "Color": "Grove"}, currency="USD", market="US")
assert validate(req, Observation(**base, amount=Decimal("298"), is_range=True), "r", T)["outcome"]["reason"] == "range_only"
assert validate(req, Observation(**base, amount=Decimal("250"), amount_basis="membership"), "r", T)["outcome"]["reason"] \
    == "conditional_price_only"

# 9. page selected something else than requested -> unresolved (no silent substitution)
wrong = validate(req, Observation(selected_options={"Size": "Full/Queen", "Color": "Grove"}, amount=Decimal("268"),
                                  currency="USD", market="US"), "r", T)
assert wrong["outcome"]["reason"] == "variant_not_found"

print("ok: 9 checks passed (recorded fixture, not a live observation)")
