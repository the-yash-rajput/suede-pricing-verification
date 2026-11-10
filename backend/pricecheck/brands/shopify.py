"""Generic adapter for ANY Shopify storefront. Onboarding a Shopify brand = a `brands` row, no code.

Primary source: /products/<handle>.js (public, all themes).
Cross-check:    the product page opened at ?variant=<id> in a US-pinned browser:
                - Shopify.currency.active / Shopify.country  -> currency + market actually applied
                - the cart form's selected variant id         -> page agrees on the variant
                - rendered price text                         -> page agrees on the amount
Per-brand config (brands.config): price_selector, rate_scope, ttl_seconds, extra condition phrases.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..core import (CONDITIONAL_ONLY, VARIANT_NOT_FOUND, Evidence, Observation, RateLimited, Request, Transient,
                    money, norm)

# Seen in themes; brand config price_selector wins. ponytail: heuristic list, per-brand selector when it misses.
DEFAULT_PRICE_SELECTORS = [
    "[data-product-price]", ".price-item--sale", ".price__current", ".product__price",
    ".product-price", "[class*='ProductPrice']", "[class*='product-price']", "[class*='price']",
]
CONDITION_PATTERNS = {
    "membership": r"[^.\n]{0,80}\b(members?|membership|insider|rewards?)\b[^.\n]{0,80}",
    "promo_code": r"[^.\n]{0,80}\b(use|with|enter|apply) (the )?(promo )?code\b[^.\n]{0,80}",
    "financing": r"[^.\n]{0,40}\b(/mo|per month|affirm|klarna|afterpay)\b[^.\n]{0,40}",
}
US_COOKIES = [("localization", "US"), ("cart_currency", "USD")]


def handle_from_url(url: str) -> str:
    m = re.search(r"/products/([^/?#]+)", urlparse(url).path)
    if not m:
        raise ValueError(f"not a Shopify product URL: {url}")
    return m.group(1)


def option_names(product: dict) -> list[str]:
    # .js: [{"name": "Color", "values": [...]}]; .json: [{"name": ..., "values": ...}] or plain strings
    return [o["name"] if isinstance(o, dict) else o for o in product["options"]]


def valid_options(product: dict) -> dict[str, list[str]]:
    names = option_names(product)
    out = {n: [] for n in names}
    for v in product["variants"]:
        for i, n in enumerate(names):
            val = v.get(f"option{i + 1}")
            if val is not None and val not in out[n]:
                out[n].append(val)
    return out


def pick_variant(product: dict, requested: dict[str, str]) -> dict | None:
    """Exact match on every option. Unknown option name or value -> None. Never a default variant."""
    names = [norm(n) for n in option_names(product)]
    want = {}
    for k, v in requested.items():
        if norm(k) not in names:
            return None
        want[names.index(norm(k)) + 1] = norm(v)
    if len(want) != len(names):          # every option must be specified, else it's ambiguous
        return None
    hits = [v for v in product["variants"]
            if all(norm(str(v.get(f"option{i}"))) == val for i, val in want.items())]
    return hits[0] if len(hits) == 1 else None


def selected_options(product: dict, variant: dict) -> dict[str, str]:
    return {n: variant.get(f"option{i + 1}") for i, n in enumerate(option_names(product))}


def observe_json(req: Request, product: dict, src_url: str) -> Observation:
    """Pure: product JSON -> Observation (no network). Used by fetch() and the tests on recorded data."""
    obs = Observation(product={"title": product.get("title"), "url": req.url.split("?")[0],
                               "id": str(product.get("id"))},
                      source={"method": "shopify_js", "url": src_url})
    v = pick_variant(product, req.variant)
    if v is None:
        obs.failure = (VARIANT_NOT_FOUND, {"requested": req.variant, "valid_options": valid_options(product),
                                           "note": "no exact match; default variant NOT substituted"})
        return obs
    obs.resolved_variant_id = str(v["id"])
    obs.selected_options = selected_options(product, v)
    obs.amount = money(v["price"])
    obs.compare_at = money(v.get("compare_at_price"))
    if v.get("quantity_price_breaks"):
        obs.conditions.append({"type": "quantity_break", "detail": v["quantity_price_breaks"]})
    if v.get("requires_selling_plan") or product.get("requires_selling_plan"):
        obs.amount_basis = "selling_plan"
        obs.failure = (CONDITIONAL_ONLY, {"note": "variant requires a selling plan (subscription)"})
    return obs


def fetch(req: Request, brand: dict, ev: Evidence) -> Observation:
    from ..browser import us_context  # lazy: pure helpers above stay testable without Playwright
    cfg = brand.get("config") or {}
    domain = brand["domain"]
    handle = handle_from_url(req.url)
    js_url = f"https://{domain}/products/{handle}.js"
    scope = cfg.get("rate_scope", "shopify-global")
    cookies = [{"name": n, "value": v, "domain": domain, "path": "/"} for n, v in US_COOKIES]

    with us_context(cookies, headed=(brand.get("config") or {}).get("headed", False)) as ctx:
        page = ctx.new_page()
        # Observed 2026-11-10: Shopify's edge answers non-browser clients (curl, Playwright's API client) with
        # 429 local_rate_limited on EVERY request, even the HTML page, while a real page navigation gets 200.
        # So the product JSON is fetched from inside the browser session (a "browser-session network response").
        _goto(page, f"https://{domain}/products/{handle}", scope, ev)
        status, body = page.evaluate("""async (u) => { const r = await fetch(u, {headers: {accept: 'application/json'}});
                                         return [r.status, await r.text()] }""", f"/products/{handle}.js")
        if status == 429:
            ev.add("http_response", "product.js.429.txt", body, excerpt=f"429 in-session: {body[:100]}")
            raise RateLimited(scope, 120, ev.items)
        if status >= 500:
            raise Transient(f"{js_url} -> {status}")
        if status != 200 or not body.lstrip().startswith("{"):
            ev.add("http_response", "product.js.txt", body, excerpt=f"HTTP {status}: {body[:200]}")
            return Observation(product={"url": req.url}, source={"method": "shopify_js", "url": js_url},
                               failure=("site_error", {"status": status, "note": "product JSON not returned"}))
        product = json.loads(body)
        obs = observe_json(req, product, js_url)
        obs.source["via"] = "in-browser fetch (same session as the page)"
        v = next((x for x in product["variants"] if str(x["id"]) == obs.resolved_variant_id), None)
        ev.add("network_json", "product.js.json", body,
               excerpt=json.dumps({k: v.get(k) for k in ("id", "title", "price", "compare_at_price", "available")})
               if v else f"options: {json.dumps(valid_options(product))}")
        if obs.failure:
            return obs

        # --- browser cross-check on the exact variant page ---
        page_url = f"https://{domain}/products/{handle}?variant={obs.resolved_variant_id}"
        _goto(page, page_url, scope, ev)
        page.wait_for_timeout(2500)  # theme JS renders the variant price
        info = page.evaluate("""() => ({
            currency: window.Shopify && Shopify.currency && Shopify.currency.active,
            country: window.Shopify && Shopify.country,
            formVariant: (document.querySelector('form[action*="/cart/add"] [name="id"]') || {}).value || null,
            url: location.href,
        })""")
        obs.currency, obs.market = info["currency"], info["country"]
        dom_price_text = _price_text(page, cfg.get("price_selector"))
        body_text = page.inner_text("body")
        ev.add("screenshot", "variant.png", page.screenshot(full_page=False))
        ev.add("dom_text", "price.txt", dom_price_text or "", excerpt=dom_price_text or "(no price element found)")
        ev.note("page_context", json.dumps(info))

        if info["formVariant"] and str(info["formVariant"]) != obs.resolved_variant_id:
            obs.failure = (VARIANT_NOT_FOUND, {"note": "page selected a different variant than requested",
                                               "page_variant": info["formVariant"], "json_variant": obs.resolved_variant_id})
        obs.cross_check = {"method": "browser_dom", "url": page_url, "amount": _first_money(dom_price_text, obs.amount),
                           "page_variant_id": info["formVariant"]}
        obs.conditions += _conditions(body_text, cfg.get("condition_phrases", []))
        return obs


def _goto(page, url: str, scope: str, ev: Evidence):
    r = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    if r and r.status == 429:
        ev.add("http_response", "page.429.txt", r.text()[:2000], excerpt=f"429 page {url}")
        raise RateLimited(scope, int(r.headers.get("retry-after", 120)), ev.items)
    if r and r.status >= 500:
        raise Transient(f"{url} -> {r.status}")


def _price_text(page, selector: str | None) -> str | None:
    for sel in ([selector] if selector else []) + DEFAULT_PRICE_SELECTORS:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 5)):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    t = el.inner_text().strip()
                    if re.search(r"\$\s?\d", t):
                        return t
            except Exception:
                continue
    return None


def _first_money(text: str | None, expected):
    """Price element text may hold both sale + compare-at ('$268 $448'). Prefer the value equal to the JSON
    amount if present (that's agreement); otherwise the first amount, which then shows up as disagreement."""
    if not text:
        return None
    vals = [money(m) for m in re.findall(r"\$\s?\d[\d,]*(?:\.\d{2})?", text)]
    return expected if expected in vals else (vals[0] if vals else None)


def _conditions(text: str, extra: list[str]) -> list[dict]:
    out = []
    pats = dict(CONDITION_PATTERNS)
    for i, p in enumerate(extra):
        pats[f"custom_{i}"] = rf"[^.\n]{{0,80}}{re.escape(p)}[^.\n]{{0,80}}"
    for kind, pat in pats.items():
        m = re.search(pat, text, re.I)
        if m:
            out.append({"type": kind, "excerpt": m.group(0).strip()[:200],
                        "note": "seen on page; not used as current_amount"})
    return out
