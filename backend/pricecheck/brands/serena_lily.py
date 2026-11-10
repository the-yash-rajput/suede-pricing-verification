"""Serena & Lily: custom (headless Next.js on Vercel). The browser is required: plain HTTP gets a 403 bot page.

The browser-dependent flow (the deep-dive in DESIGN.md):
  1. open the requested URL in a US-pinned browser
  2. read the product JSON the page embeds in the options container (childProducts = every size x color,
     each with its own URL id; selected = what this page has selected; displayPrice.prices = list/sale cents)
  3. map the requested options -> child id (exact). No child -> unresolved, valid combos listed.
  4. if the page shows a different child (e.g. the base URL redirected to a default variant), navigate to the
     requested child's URL, then RE-READ the selected options from the page. Never assume the navigation worked.
  5. amount = sale price if present, else list. Cross-check against the rendered price DOM.
Seen 2026-11-10: Full/Queen Coastal Blue $268 (list $448); King/Cal King Lark $298 (list $498).
"""
from __future__ import annotations

import json
import re

from ..core import (RANGE_ONLY, SITE_ERROR, VARIANT_NOT_FOUND, Evidence, Observation, Request, Transient, money,
                    norm)

JSON_SEL = '[class*="ProductOptions_productOptionsContainer"] script'
SALE_SEL = '[class*="ProductPrice_salesPrice"]'
LIST_SEL = '[class*="ProductPrice_listedPrice"]'
WRAP_SEL = '[class*="ProductPrice_productPriceWrapper"]'
AFFIRM_SEL = '[class*="ProductOptions_affirmWrapper"]'


def _opts(variants: list[dict]) -> dict[str, str]:
    return {v["name"].strip().capitalize(): v["value"].strip() for v in variants or []}


def _match(child_opts: dict, requested: dict) -> bool:
    c = {norm(k): norm(v) for k, v in child_opts.items()}
    return len(c) == len(requested) and all(c.get(norm(k)) == norm(v) for k, v in requested.items())


def _read(page) -> dict | None:
    el = page.query_selector(JSON_SEL)
    if not el:
        return None
    try:
        return json.loads(el.text_content())
    except json.JSONDecodeError:
        return None


def _text(page, sel) -> str | None:
    el = page.query_selector(sel)
    return el.inner_text().strip() if el else None


def fetch(req: Request, brand: dict, ev: Evidence) -> Observation:
    from ..browser import us_context

    base = re.sub(r"/[^/]+/?$", "", req.url.split("?")[0])  # .../products/delancey-quilt
    with us_context() as ctx:
        page = ctx.new_page()
        r = page.goto(req.url, wait_until="domcontentloaded", timeout=45_000)
        status = r.status if r else None
        if status and status >= 500:
            raise Transient(f"{req.url} -> {status}")
        try:
            page.wait_for_selector(JSON_SEL, state="attached", timeout=20_000)
        except Exception:
            ev.add("screenshot", "blocked.png", page.screenshot())
            body = page.inner_text("body")[:2000] if page.query_selector("body") else ""
            ev.add("dom_text", "body.txt", body, excerpt=f"HTTP {status}: {body[:200]}")
            return Observation(product={"url": req.url}, source={"method": "browser_embedded_json", "url": req.url},
                               failure=(SITE_ERROR, {"status": status, "note": "product data not found: bot wall, "
                                                     "error page, or page structure changed"}))
        data = _read(page)
        if not data:
            return Observation(product={"url": req.url}, failure=(SITE_ERROR, {"note": "embedded product JSON unparsable"}))

        children = {c["netsuiteId"]: _opts(c.get("variants")) for c in data.get("childProducts") or []}
        target = next((cid for cid, o in children.items() if _match(o, req.variant)), None)
        product = {"title": data.get("name"), "url": req.url.split("?")[0], "id": data.get("sku")}
        if target is None:
            ev.add("embedded_json", "product.json", json.dumps({"childProducts": children}, indent=1),
                   excerpt=f"valid combos: {list(children.values())}")
            return Observation(product=product, source={"method": "browser_embedded_json", "url": page.url},
                               failure=(VARIANT_NOT_FOUND, {"requested": req.variant,
                                                            "valid_combinations": list(children.values()),
                                                            "note": "no exact child product; default NOT substituted"}))

        # variant selection: go to the requested child's page if this page shows another one
        landed = data.get("selected", {}).get("netsuiteId")
        if landed != target:
            ev.note("variant_selection", f"landed on {landed} ({children.get(landed)}); navigating to {target}")
            page.goto(f"{base}/{target}", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_selector(JSON_SEL, state="attached", timeout=20_000)
            data = _read(page) or {}
        page.wait_for_timeout(1500)  # client-side price render

        sel = data.get("selected", {})
        prices = {p["type"]: p["amount"] for p in (data.get("displayPrice") or {}).get("prices") or []}
        list_amt, sale_amt = money(prices.get("list")), money(prices.get("sale"))
        dom_sale, dom_list, dom_wrap = _text(page, SALE_SEL), _text(page, LIST_SEL), _text(page, WRAP_SEL)
        affirm = _text(page, AFFIRM_SEL)

        ev.add("embedded_json", "product.json",
               json.dumps({"selected": {"netsuiteId": sel.get("netsuiteId"), "variants": sel.get("variants"),
                                        "isAvailableForPurchase": sel.get("isAvailableForPurchase")},
                           "displayPrice": data.get("displayPrice")}, indent=1),
               excerpt=json.dumps({"selected": sel.get("variants"), "prices": prices}))
        ev.add("dom_text", "price.txt", f"wrapper: {dom_wrap}\nsale: {dom_sale}\nlist: {dom_list}\naffirm: {affirm}",
               excerpt=f"{dom_wrap} | affirm: {affirm}")
        ev.add("screenshot", "variant.png", page.screenshot())

        obs = Observation(
            product=product,
            selected_options=_opts(sel.get("variants")),   # re-read from the page, not the request
            resolved_variant_id=sel.get("netsuiteId"),
            amount=sale_amt or list_amt,
            compare_at=list_amt if sale_amt else None,
            # ponytail: no currency field on the page; S&L sells US-only in $. Inference recorded in source.
            currency="USD" if (dom_wrap or "").count("$") else None, market="US",
            is_range=bool(re.search(r"\$[\d,.]+\s*-\s*\$", dom_wrap or "")),
            source={"method": "browser_embedded_json", "url": page.url,
                    "currency_basis": "inferred: US-only storefront, $-formatted, no currency field"},
            cross_check={"method": "browser_dom", "amount": money(dom_sale or dom_list)},
        )
        for m in (data.get("displayPrice") or {}).get("promoMessages") or []:
            obs.conditions.append({"type": "promo_banner", "excerpt": m.get("message"),
                                   "note": "sitewide banner, no code required; already reflected in sale price"})
        if affirm:
            obs.conditions.append({"type": "financing", "excerpt": affirm, "note": "monthly financing, ignored"})
        if sel.get("netsuiteId") != target:
            obs.failure = (VARIANT_NOT_FOUND, {"note": "page did not select the requested child",
                                               "expected": target, "page": sel.get("netsuiteId")})
        elif obs.is_range:
            obs.failure = (RANGE_ONLY, {"dom": dom_wrap})
        elif sel.get("isAvailableForPurchase") is False:
            obs.conditions.append({"type": "availability", "excerpt": "not available for purchase",
                                   "note": "availability is out of scope; price still reported"})
        return obs
