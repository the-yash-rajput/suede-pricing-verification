"""Shared logic: request/observation types, validation, evidence. No brand code, no DB, no network."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

EVIDENCE_ROOT = Path(__file__).resolve().parent.parent / "evidence"

# outcome.reason values for unresolved results
VARIANT_NOT_FOUND = "variant_not_found"      # requested options don't exist / don't match what the page selected
VARIANT_UNAVAILABLE = "variant_unavailable"  # exists but can't be selected (no price shown for it)
RANGE_ONLY = "range_only"                    # only a price range is visible, never pick an end of it
PRICE_NOT_FOUND = "price_not_found"
CONDITIONAL_ONLY = "conditional_price_only"  # only a member / promo-code price was found
WRONG_MARKET = "wrong_market"                # not US / USD
SOURCES_DISAGREE = "sources_disagree"        # structured source vs rendered page
SITE_ERROR = "site_error"                    # error page, timeouts after retries
BOT_BLOCKED = "bot_blocked"                  # bot-protection vendor blocked us: no retry, ops handoff
RATE_LIMITED = "rate_limited"
NO_ADAPTER = "no_adapter"


class RateLimited(Exception):
    """Adapter saw a 429 / throttle. The caller sets a cooldown for `scope`; no immediate retry."""
    def __init__(self, scope: str, retry_after: int, evidence: list | None = None):
        super().__init__(f"rate limited on {scope}, retry after {retry_after}s")
        self.scope, self.retry_after, self.evidence = scope, retry_after, evidence or []


class Transient(Exception):
    """Timeout / 5xx / navigation hiccup. Safe to retry."""
    def __init__(self, msg: str, evidence: list | None = None):
        super().__init__(msg)
        self.evidence = evidence or []


@dataclass
class Request:
    brand: str
    url: str
    variant: dict[str, str]   # option name -> value, e.g. {"Size": "103\"W", "Color": "..."}
    quantity: int = 1


@dataclass
class Observation:
    """What an adapter saw. Facts only; validate() decides the outcome."""
    product: dict = field(default_factory=dict)          # title, url, id
    selected_options: dict | None = None                 # options the SOURCE reports as selected, not the request
    resolved_variant_id: str | None = None
    amount: Decimal | None = None                        # the price the adapter believes is the current public selling price
    amount_basis: str = "current_selling"                # basis of `amount` if the adapter could only find a conditional one
    compare_at: Decimal | None = None
    currency: str | None = None
    market: str | None = None
    is_range: bool = False
    conditions: list[dict] = field(default_factory=list)  # member / promo / financing prices seen, never the amount
    source: dict = field(default_factory=dict)
    cross_check: dict | None = None                      # {"method", "amount": Decimal|None}
    failure: tuple[str, dict] | None = None              # adapter-detected (reason, detail)
    evidence: list[dict] = field(default_factory=list)


def new_run_id() -> str:
    return "r-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def norm(v: str) -> str:
    # ponytail: casefold + collapse whitespace + unify quote marks; brands that rename options need ops, not fuzz
    return re.sub(r"\s+", " ", v.replace("”", '"').replace("″", '"')).strip().casefold()


def options_match(requested: dict, selected: dict | None) -> bool:
    if not selected:
        return False
    sel = {norm(k): norm(str(v)) for k, v in selected.items()}
    return all(sel.get(norm(k)) == norm(v) for k, v in requested.items()) and len(requested) > 0


def money(x) -> Decimal | None:
    """'$2,598.00' / '2598' / 259800 (cents, int) -> Decimal. Ints are treated as cents (Shopify)."""
    if x is None:
        return None
    if isinstance(x, int):
        return (Decimal(x) / 100).quantize(Decimal("0.01"))
    m = re.search(r"\d[\d,]*(?:\.\d{1,2})?", str(x))
    return Decimal(m.group(0).replace(",", "")).quantize(Decimal("0.01")) if m else None


class Evidence:
    """Writes evidence files for one brand in one run; returns items for supporting_evidence."""
    def __init__(self, run_id: str, brand: str):
        self.dir = EVIDENCE_ROOT / run_id / slug(brand)
        self.items: list[dict] = []

    def add(self, kind: str, name: str, content: str | bytes, excerpt: str | None = None, **extra) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = content.encode() if isinstance(content, str) else content
        p = self.dir / name
        p.write_bytes(data)
        item = {"kind": kind, "path": str(p.relative_to(EVIDENCE_ROOT.parent)),
                "sha256": hashlib.sha256(data).hexdigest(), "captured_at": now_iso()}
        if excerpt is not None:
            item["excerpt"] = excerpt[:500]
        item.update(extra)
        self.items.append(item)
        return item

    def note(self, kind: str, excerpt: str, **extra) -> dict:
        item = {"kind": kind, "excerpt": excerpt[:500], "captured_at": now_iso(), **extra}
        self.items.append(item)
        return item


def _s(d: Decimal | None) -> str | None:
    return None if d is None else f"{d:.2f}"


def validate(req: Request, obs: Observation, run_id: str, observed_at: str) -> dict:
    """Turn an observation into the brief's 11-field result. Unresolved beats guessing, every time."""
    reason, detail = None, {}
    if obs.failure:
        reason, detail = obs.failure
    elif not options_match(req.variant, obs.selected_options):
        reason = VARIANT_NOT_FOUND
        detail = {"requested": req.variant, "source_selected": obs.selected_options}
    elif obs.is_range:
        reason = RANGE_ONLY
    elif obs.amount is None:
        reason = PRICE_NOT_FOUND
    elif obs.amount_basis != "current_selling":
        reason, detail = CONDITIONAL_ONLY, {"basis_found": obs.amount_basis}
    elif obs.currency != "USD" or obs.market != "US":
        reason, detail = WRONG_MARKET, {"currency": obs.currency, "market": obs.market}
    elif obs.cross_check and obs.cross_check.get("amount") != obs.amount:
        reason = SOURCES_DISAGREE
        detail = {"primary": _s(obs.amount), "cross_check": _s(obs.cross_check.get("amount")),
                  "cross_check_method": obs.cross_check.get("method")}

    ok = reason is None
    on_sale = bool(ok and obs.compare_at is not None and obs.compare_at > obs.amount)
    source = dict(obs.source)
    if obs.cross_check:
        cc = dict(obs.cross_check)
        cc["amount"] = _s(cc.get("amount"))
        cc["agrees"] = obs.cross_check.get("amount") == obs.amount if obs.amount is not None else None
        source["cross_check"] = cc

    return {
        "brand": req.brand,
        "product": obs.product or {"url": req.url},
        "requested_variant": {"options": req.variant, "quantity": req.quantity,
                              "resolved_variant_id": obs.resolved_variant_id,
                              "source_selected_options": obs.selected_options,
                              "matched": options_match(req.variant, obs.selected_options)},
        "market": obs.market,
        "currency": obs.currency,
        "current_amount": _s(obs.amount) if ok else None,
        "price_basis": {"type": "current_selling" if ok else "unknown",
                        # compare-at is only meaningful when it's above the selling price
                        "compare_at_amount": _s(obs.compare_at) if on_sale else None,
                        "on_sale": on_sale if ok else None,
                        "conditions": obs.conditions},
        "source": source,
        "observation_time": observed_at,
        "outcome": {"status": "resolved" if ok else "unresolved", "reason": reason,
                    "detail": detail or None, "from_cache": False, "run_id": run_id},
        "supporting_evidence": obs.evidence,
    }


def unresolved(req: Request, reason: str, detail: dict, run_id: str, evidence: list | None = None,
               source: dict | None = None) -> dict:
    """Unresolved result for failures that happen before/around an adapter (no adapter, rate limit, crash)."""
    obs = Observation(product={"url": req.url}, failure=(reason, detail), source=source or {},
                      evidence=evidence or [])
    return validate(req, obs, run_id, now_iso())


def dumps(result: dict) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)
