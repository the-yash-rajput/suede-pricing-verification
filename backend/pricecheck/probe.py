"""Onboarding probe: what platform is this brand on, and which approach should it get?

Read-only HTTP, a handful of requests. Proposes:
  shopify_ucp -> Shopify product JSON works AND /.well-known/ucp publishes a profile  -> adapter 'shopify'
  shopify     -> Shopify product JSON works, no UCP                                  -> adapter 'shopify'
  custom      -> anything else (headless, bot wall, error bodies)                      -> adapter NULL until built
Ops reviews the evidence and can override before saving.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .browser import UA
from .core import now_iso

CHALLENGE = re.compile(r"just a moment|cf-chl|captcha|access denied|px-captcha|are you a human", re.I)


def _get(url: str, timeout=15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(200_000).decode("utf-8", "replace")
            return {"url": url, "status": r.status, "headers": dict(r.headers), "body": body}
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "headers": dict(e.headers or {}),
                "body": e.read(20_000).decode("utf-8", "replace")}
    except Exception as e:
        return {"url": url, "status": None, "headers": {}, "body": "", "error": repr(e)}


def _json(body: str):
    try:
        return json.loads(body)
    except Exception:
        return None


def _brief(r: dict) -> dict:
    keep = ("server", "x-shopid", "x-shopify-stage", "powered-by", "x-powered-by", "x-vercel-id", "cf-ray",
            "content-type", "retry-after")
    h = {k.lower(): v for k, v in r["headers"].items()}
    return {"url": r["url"], "status": r["status"], "headers": {k: h[k] for k in keep if k in h},
            "body_head": r["body"][:300], **({"error": r["error"]} if "error" in r else {})}


def probe(domain: str, sample_url: str) -> dict:
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    page = _get(sample_url)
    signals, evidence = [], {"probed_at": now_iso(), "page": _brief(page)}

    # Shopify product JSON
    m = re.search(r"/products/([^/?#]+)", urlparse(sample_url).path)
    shopify_json = None
    if m:
        js = _get(f"https://{domain}/products/{m.group(1)}.js")
        evidence["product_js"] = _brief(js)
        data = _json(js["body"])
        if js["status"] == 200 and isinstance(data, dict) and "variants" in data:
            shopify_json = True
            signals.append(f"product .js returned {len(data['variants'])} variants")
        elif js["status"] == 429:
            signals.append("product .js rate-limited (429): Shopify edge throttle, likely Shopify; re-probe later")

    # UCP profile
    ucp = _get(f"https://{domain}/.well-known/ucp")
    prof = _json(ucp["body"]) if ucp["status"] == 200 else None
    evidence["ucp"] = _brief(ucp)
    ucp_caps, ucp_endpoint = None, None
    if isinstance(prof, dict):
        txt = json.dumps(prof)
        ucp_caps = sorted(set(re.findall(r'"(dev\.ucp\.[a-z_.]+|[a-z_]+\.[a-z_.]+)"', txt)))[:60] or list(prof)[:30]
        mm = re.search(r'https://[^"]+/ucp/[^"]*', txt)
        ucp_endpoint = mm.group(0) if mm else None
        signals.append("UCP profile published")

    hdr = {k.lower(): v for k, v in page["headers"].items()}
    is_shopify_page = bool(re.search(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", page["body"])) or "x-shopid" in hdr
    if is_shopify_page:
        signals.append("Shopify markers in page HTML/headers")
    if "__NEXT_DATA__" in page["body"] or "x-vercel-id" in hdr or hdr.get("server", "").lower() == "vercel":
        signals.append("Next.js / Vercel (headless)")
    if page["status"] in (403, 503) and CHALLENGE.search(page["body"]):
        signals.append(f"bot challenge on plain HTTP ({page['status']}); needs a real browser or ops")
    if page["status"] == 200 and re.search(r'"error"\s*:\s*"Internal Server Error"', page["body"][:500]):
        signals.append("HTTP 200 with an error body: not a product page")

    if shopify_json:
        approach = "shopify_ucp" if prof else "shopify"
        adapter, custom_method = "shopify", None
    else:
        approach, adapter = "custom", None
        has_ld = '"@type":"Product"' in page["body"].replace(" ", "") and page["status"] == 200
        custom_method = "page_structured" if has_ld else ("browser" if page["status"] in (200, 403) else "manual")
        signals.append(f"suggested custom rung: {custom_method}")

    return {"domain": domain, "approach": approach, "adapter": adapter, "custom_method": custom_method,
            "ucp_endpoint": ucp_endpoint, "ucp_capabilities": ucp_caps, "signals": signals,
            "probe_evidence": evidence}


if __name__ == "__main__":
    import sys
    print(json.dumps(probe(sys.argv[1], sys.argv[2]), indent=2))
