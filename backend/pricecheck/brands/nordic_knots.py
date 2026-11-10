"""Nordic Knots: custom (headless Next.js on Vercel, US market under /us, cookie NEXT_COUNTRY=US).

STATUS: the product extraction is NOT yet verified against a live product page. From India egress
(Vercel edge bom1) every page returned HTTP 200 with body {"error":"Internal Server Error","status":500},
in curl and real Chrome (2026-11-10). Plan: re-run from a US VPN, pick a rug with size-priced variants,
then pin the extraction below to what the page actually exposes.

What it does today:
  - detects the error body (HTTP 200 is not success) -> Transient -> retried -> unresolved site_error + evidence
  - otherwise tries schema.org JSON-LD offers (common on Next.js storefronts): each offer's name/sku must
    contain every requested option value exactly once-matched; ambiguous or none -> unresolved.
"""
from __future__ import annotations

import json
import re

from ..core import SITE_ERROR, VARIANT_NOT_FOUND, Evidence, Observation, Request, Transient, money, norm

ERROR_BODY = re.compile(r'"error"\s*:\s*"Internal Server Error"')


def _offers(page) -> tuple[dict | None, list[dict]]:
    for el in page.query_selector_all('script[type="application/ld+json"]'):
        try:
            d = json.loads(el.text_content())
        except json.JSONDecodeError:
            continue
        for node in d if isinstance(d, list) else d.get("@graph", [d]):
            if isinstance(node, dict) and node.get("@type") in ("Product", "ProductGroup"):
                offers = node.get("offers") or []
                if isinstance(offers, dict):
                    offers = offers.get("offers") or [offers]
                for v in node.get("hasVariant") or []:
                    o = v.get("offers") or {}
                    offers.append({**(o[0] if isinstance(o, list) else o), "name": v.get("name"), "sku": v.get("sku")})
                return node, offers
    return None, []


def fetch(req: Request, brand: dict, ev: Evidence) -> Observation:
    from ..browser import us_context

    cookies = [{"name": "NEXT_COUNTRY", "value": "US", "domain": ".nordicknots.com", "path": "/"},
               {"name": "NEXT_LANGUAGE", "value": "en", "domain": ".nordicknots.com", "path": "/"}]
    with us_context(cookies) as ctx:
        page = ctx.new_page()
        r = page.goto(req.url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(2000)
        body = page.inner_text("body") if page.query_selector("body") else ""
        status = r.status if r else None
        if ERROR_BODY.search(body[:500]) or (status and status >= 500):
            ev.add("dom_text", f"error_body_{len(ev.items)}.txt", body[:2000],
                   excerpt=f"HTTP {status} with body: {body[:150]}", headers={k: v for k, v in (r.headers if r else {}).items()
                                                                           if k in ("server", "x-vercel-id", "date")})
            ev.add("screenshot", f"error_{len(ev.items)}.png", page.screenshot())
            raise Transient(f"HTTP {status} but error body (not a product page)")

        node, offers = _offers(page)
        product = {"title": (node or {}).get("name"), "url": req.url.split("?")[0], "id": (node or {}).get("sku")}
        ev.add("screenshot", "page.png", page.screenshot())
        if not node:
            ev.add("dom_text", "body.txt", body[:3000], excerpt=body[:200])
            return Observation(product=product, source={"method": "browser_jsonld", "url": page.url},
                               failure=(SITE_ERROR, {"note": "no JSON-LD Product on page; extraction not yet "
                                                     "pinned to the live page (see adapter STATUS)"}))
        want = [norm(v) for v in req.variant.values()]
        hits = [o for o in offers if all(w in norm(f"{o.get('name', '')} {o.get('sku', '')}") for w in want)]
        ev.add("structured_data", "jsonld.json", json.dumps(node, indent=1)[:50_000],
               excerpt=json.dumps([{k: o.get(k) for k in ("name", "sku", "price", "priceCurrency")} for o in offers])[:500])
        if len(hits) != 1:
            return Observation(product=product, source={"method": "browser_jsonld", "url": page.url},
                               failure=(VARIANT_NOT_FOUND, {"requested": req.variant, "matches": len(hits),
                                                            "offers": [o.get("name") for o in offers][:40]}))
        o = hits[0]
        return Observation(product=product, selected_options=dict(req.variant),  # matched on the offer's own name
                           resolved_variant_id=o.get("sku"), amount=money(str(o.get("price"))),
                           currency=o.get("priceCurrency"), market="US" if "/us" in page.url else None,
                           source={"method": "browser_jsonld", "url": page.url, "offer_name": o.get("name")})
