"""Optional extension: public shipping quote for one Shopify product to New York, NY 10001, qty 1.

Source: Shopify's guest-cart calculator (/cart/shipping_rates.json), called from inside a US-pinned browser
session (Shopify's edge 429s non-browser clients). The cart lives in an ephemeral browser context: no account,
no address beyond city/state/ZIP, no checkout, no order. Unknown shipping is null, never 0.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from . import db
from .brands.shopify import US_COOKIES, _goto, handle_from_url, pick_variant, valid_options
from .core import Evidence, RateLimited, Request, money, now_iso

DEST = {"city": "New York", "region": "NY", "postal_code": "10001", "country": "US"}
_ADDR = {"shipping_address[zip]": "10001", "shipping_address[province]": "New York",
         "shipping_address[country]": "United States"}
FETCH = """async ([u, method, body]) => {
  const r = await fetch(u, {method, headers: {'content-type': 'application/json', accept: 'application/json'},
                            body: body ? JSON.stringify(body) : undefined});
  return [r.status, await r.text()] }"""


def _rates(body: dict) -> list[dict]:
    return [{"amount": f"{money(r.get('price')):.2f}" if money(r.get("price")) is not None else None,
             "currency": r.get("currency"), "service": r.get("presentment_name") or r.get("name"),
             "delivery_days": r.get("delivery_days"), "code": r.get("code")}
            for r in body.get("shipping_rates") or []]


def quote(req: Request, brand: dict, run_id: str) -> dict:
    from .browser import us_context

    ev = Evidence(run_id, req.brand)
    domain, handle = brand["domain"], handle_from_url(req.url)
    scope = (brand.get("config") or {}).get("rate_scope", "shopify-global")
    out = {"brand": req.brand, "product": {"url": req.url.split("?")[0]}, "requested_variant": req.variant,
           "variant_id": None, "quantity": 1, "destination": DEST, "outcome": {"status": "unresolved",
           "reason": None, "run_id": run_id}, "shipping_amount": None, "rates": [], "applies_per": "basket",
           "basis": "cart_calculator_quote", "missing_fields": [], "human_action": None,
           "observation_time": now_iso(), "evidence": ev.items}

    def fail(reason, action, **detail):
        out["outcome"].update(reason=reason, detail=detail or None)
        out["human_action"] = action
        return out

    wait = db.cooldown_remaining(scope)
    if wait:
        return fail("rate_limited", f"rerun after {wait}s (Shopify cooldown on {scope})", retry_after_seconds=wait)

    cookies = [{"name": n, "value": v, "domain": domain, "path": "/"} for n, v in US_COOKIES]
    try:
        with us_context(cookies) as ctx:
            page = ctx.new_page()
            _goto(page, f"https://{domain}/products/{handle}", scope, ev)
            call = lambda u, m="GET", b=None: page.evaluate(FETCH, [u, m, b])  # noqa: E731

            st, body = call(f"/products/{handle}.js")
            if st != 200:
                return fail("site_error", "ops: check the product page", status=st, body=body[:200])
            product = json.loads(body)
            v = pick_variant(product, req.variant)
            if v is None:   # nothing added to the cart; never a default variant
                return fail("variant_not_found", "correct the variant and rerun",
                            requested=req.variant, valid_options=valid_options(product))
            out["variant_id"], out["product"]["title"] = str(v["id"]), product.get("title")

            st, body = call("/cart/add.js", "POST", {"items": [{"id": v["id"], "quantity": 1}]})
            ev.add("network_json", "cart_add.json", body, excerpt=f"HTTP {st}: {body[:200]}")
            if st != 200:
                return fail("site_error", "ops: add the variant to a cart by hand", status=st)

            q = "/cart/shipping_rates.json?" + urlencode(_ADDR)
            st, body = call(q)
            if st == 200 and not json.loads(body).get("shipping_rates"):
                # calculated / freight carriers answer asynchronously
                call("/cart/prepare_shipping_rates.json?" + urlencode(_ADDR), "POST")
                for _ in range(3):
                    page.wait_for_timeout(2000)
                    st, body = call("/cart/async_shipping_rates.json?" + urlencode(_ADDR))
                    if st == 200 and json.loads(body).get("shipping_rates"):
                        break
            ev.add("network_json", "shipping_rates.json", body, excerpt=f"HTTP {st}: {body[:300]}")
            cart_st, cart = call("/cart.js")
            ev.add("network_json", "cart.json", cart, excerpt=f"HTTP {cart_st}: item_count="
                   f"{json.loads(cart).get('item_count') if cart_st == 200 else '?'}")

            if st == 429:
                db.set_cooldown(scope, 120, "429")
                return fail("rate_limited", "rerun after the cooldown", status=st)
            data = json.loads(body) if body.lstrip().startswith("{") else {}
            if st == 422:
                out["missing_fields"] = sorted(data)
                return fail("address_incomplete", f"supply {out['missing_fields']} for the destination", errors=data)
            rates = _rates(data)
            out["rates"] = rates
            if st != 200 or not rates:
                return fail("no_rates", "ops: open a guest cart with this variant, enter ZIP 10001, record the "
                            "shipping line (method + amount) and a screenshot against this run_id", status=st)
            if len(rates) == 1:
                out["shipping_amount"] = rates[0]["amount"]
            out["outcome"].update(status="resolved", detail={"note": "pre-checkout cart estimate before tax; "
                                  "per-item vs per-basket not established from one 1-unit quote" +
                                  ("" if len(rates) == 1 else "; several services listed, none chosen")})
            return out
    except RateLimited as e:
        db.set_cooldown(e.scope, e.retry_after, "429")
        return fail("rate_limited", f"rerun after {e.retry_after}s", scope=e.scope)
