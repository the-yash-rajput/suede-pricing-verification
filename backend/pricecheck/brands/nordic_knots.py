"""Nordic Knots: custom (headless Next.js on Vercel, cart/pricing on Centra). US market under /us.

Verified live 2026-11-11 on Grand – Milano Green (/us/product/grand-milano-green):
  - JSON-LD Product: one offer per `size` ("5'x8'" -> 995, "6'x9'" -> 1295 ...), priceCurrency USD. This is
    server-rendered from the /us PATH, not from the shopper's market.
  - size picker: button[aria-haspopup=listbox][aria-label^="Select Size"] -> [role=option] rows; picking one moves
    the URL to /<handle>/<5x8> and sets the button text.
  - rendered price: [aria-live=polite] next to the <h1>, e.g. "995 CHF".
  - the session market comes from Centra (GET nordicknots.centra.com/api/checkout/selection -> location.country,
    selection.currency), chosen from the egress IP (cookie vercelIpCountry). From our egress it says SG / CHF even
    on /us with NEXT_COUNTRY=US and ?country=us. No on-site country selector exists to change it.
  => amount from JSON-LD, but currency/market from the SESSION (Centra, then DOM). validate() turns SG/CHF into
     wrong_market. Reporting the JSON-LD "USD" alone would be a silent wrong answer.

Flow: open URL -> error-body check (HTTP 200 is not success) -> exact offer by size (no default) -> select the size in
the picker if the page shows another -> re-read picker + URL -> DOM price + Centra selection -> Observation.
"""
from __future__ import annotations

import json
import re

from ..core import SITE_ERROR, VARIANT_NOT_FOUND, Evidence, Observation, Request, Transient, money, norm

ERROR_BODY = re.compile(r'"error"\s*:\s*"Internal Server Error"')
PICKER = 'button[aria-haspopup="listbox"][aria-label^="Select Size"]'
CENTRA = "centra.com/api/checkout/selection"
# price block is the [aria-live] sibling of the product <h1>
DOM_PRICE_JS = """() => { const h = document.querySelector('h1');
  let c = h; for (let i = 0; i < 4 && c; i++) { const p = c.querySelector('[aria-live=polite]'); if (p) return p.innerText; c = c.parentElement; }
  return null; }"""
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


def _offers(page) -> tuple[dict | None, list[dict]]:
    for el in page.query_selector_all('script[type="application/ld+json"]'):
        try:
            d = json.loads(el.text_content())
        except json.JSONDecodeError:
            continue
        for node in d if isinstance(d, list) else d.get("@graph", [d]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                offers = node.get("offers") or []
                return node, [offers] if isinstance(offers, dict) else offers
    return None, []


def _dom_currency(txt: str | None) -> str | None:
    if not txt:
        return None
    m = re.search(r"\b[A-Z]{3}\b", txt)
    return m.group(0) if m else next((c for s, c in SYMBOLS.items() if s in txt), None)


def _centra(responses) -> dict | None:
    for r in reversed(responses):  # latest selection wins (it is re-fetched after a size change)
        if CENTRA in r.url and r.request.method == "GET":
            try:
                d = r.json()
            except Exception:
                continue
            loc, sel = d.get("location") or {}, d.get("selection") or {}
            return {"country": loc.get("country"), "market": loc.get("market"), "pricelist": loc.get("pricelist"),
                    "currency": sel.get("currency") or loc.get("currency"), "url": r.url}
    return None


def fetch(req: Request, brand: dict, ev: Evidence) -> Observation:
    from ..browser import us_context

    cookies = [{"name": "NEXT_COUNTRY", "value": "US", "domain": ".nordicknots.com", "path": "/"},
               {"name": "NEXT_LANGUAGE", "value": "en", "domain": ".nordicknots.com", "path": "/"}]
    with us_context(cookies, headed=(brand.get("config") or {}).get("headed", False)) as ctx:
        page = ctx.new_page()
        responses = []
        page.on("response", lambda resp: responses.append(resp))  # ponytail: bodies read after navigation; .json() in the handler deadlocks sync Playwright
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
        product = {"title": (node or {}).get("name"), "url": req.url.split("?")[0], "id": (node or {}).get("identifier")}
        src = {"method": "browser_jsonld", "url": page.url}
        if not node:
            ev.add("screenshot", "page.png", page.screenshot())
            ev.add("dom_text", "body.txt", body[:3000], excerpt=body[:200])
            return Observation(product=product, source=src,
                               failure=(SITE_ERROR, {"note": "no JSON-LD Product on page: page structure changed?"}))
        ev.add("structured_data", "jsonld.json", json.dumps(node, indent=1)[:50_000],
               excerpt=json.dumps([{k: o.get(k) for k in ("size", "sku", "price", "priceCurrency")} for o in offers])[:500])

        sizes = [o.get("size") for o in offers]
        want = req.variant.get("Size") if set(req.variant) == {"Size"} else None
        hits = [o for o in offers if want and norm(o.get("size") or "") == norm(want)]
        if len(hits) != 1:
            return Observation(product=product, source=src,
                               failure=(VARIANT_NOT_FOUND, {"requested": req.variant, "matches": len(hits),
                                                            "valid_options": {"Size": sizes},
                                                            "note": "exact size required; default NOT substituted"}))
        offer = hits[0]

        # variant selection in the browser: the page must show the requested size, not just the URL we asked for
        picker = page.locator(PICKER).first
        shown = picker.inner_text().strip() if picker.count() else None
        if norm(shown or "") != norm(want):
            ev.note("variant_selection", f"picker showed {shown!r}; selecting {want!r}")
            picker.click()
            opts = page.locator('[role="option"]')
            labels = [t.split("\n")[0].strip() for t in opts.all_inner_texts()]  # "5'x8'\n\nAvailable now"
            idx = [i for i, t in enumerate(labels) if norm(t) == norm(want)]
            if len(idx) != 1:
                return Observation(product=product, source=src,
                                   failure=(VARIANT_NOT_FOUND, {"requested": req.variant, "note": "size not in picker",
                                                                "picker_options": labels}))
            opts.nth(idx[0]).click()
            page.wait_for_timeout(1000)
            shown = picker.inner_text().strip()

        # price + Centra selection render client-side; the price only appears once Centra answered
        try:
            page.wait_for_function(f"() => !!({DOM_PRICE_JS})()", timeout=15_000)
        except Exception:
            pass  # no price rendered -> cross-check None -> validate() won't resolve
        dom_price = page.evaluate(DOM_PRICE_JS)
        centra = _centra(responses)
        ev.add("dom_text", "price.txt", f"picker: {shown}\nprice: {dom_price}\nurl: {page.url}",
               excerpt=f"picker {shown!r} | price {dom_price!r}")
        if centra:
            ev.add("network", "centra_selection.json", json.dumps(centra, indent=1),
                   excerpt=f"Centra session market: country={centra['country']} currency={centra['currency']} "
                           f"pricelist={centra['pricelist']}")
        ev.add("screenshot", "variant.png", page.screenshot())

        # currency/market = what THIS session would be charged in; JSON-LD's USD only reflects the /us path
        session_currency = (centra or {}).get("currency") or _dom_currency(dom_price)
        return Observation(
            product=product,
            selected_options={"Size": shown} if shown else None,  # re-read from the page
            resolved_variant_id=offer.get("sku"),
            amount=money(str(offer.get("price"))),
            currency=session_currency,
            market=(centra or {}).get("country"),
            source={**src, "url": page.url, "jsonld_currency": offer.get("priceCurrency"),
                    "session": centra, "currency_basis": "Centra session selection, else rendered price"},
            cross_check={"method": "browser_dom", "amount": money(dom_price)},
        )
