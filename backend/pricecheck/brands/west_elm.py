"""West Elm (Williams-Sonoma): custom stack behind Akamai. The harder 3rd brand from the brief.

Probe 2026-11-10T22:00Z (from India): plain HTTP gets 403 "West Elm: 403 - Restricted Access", server
AkamaiNetStorage, on the product page, /products/<handle>.js and /.well-known/ucp alike.

Flow, deliberately small:
  1. ONE navigation in the US-pinned browser (headed when config.headed). No retries, no evasion, no CAPTCHA solving.
  2. Blocked (403 / Akamai or captcha markers) -> BOT_BLOCKED with screenshot, body text and cookie NAMES as evidence.
     service.verify then pauses the brand (throttle row) so later requests don't touch the site; ops hands off.
  3. Rendered -> save JSON-LD / title as evidence and return SITE_ERROR: the price extraction is not built because
     the rendered structure has never been observed. Never guess a price from an unverified page.
"""
from __future__ import annotations

import json
import re

from ..core import BOT_BLOCKED, SITE_ERROR, Evidence, Observation, Request, Transient

BLOCK = re.compile(r"restricted access|access denied|errors\.edgesuite\.net|captcha|px-captcha|are you a human", re.I)
SOURCE = "browser_page"


def fetch(req: Request, brand: dict, ev: Evidence) -> Observation:
    from ..browser import us_context

    cfg = brand.get("config") or {}
    with us_context(headed=cfg.get("headed", False)) as ctx:
        page = ctx.new_page()
        r = page.goto(req.url, wait_until="domcontentloaded", timeout=45_000)
        status = r.status if r else None
        if status and status >= 500:
            raise Transient(f"{req.url} -> {status}")
        page.wait_for_timeout(2500)  # let any challenge script run once; we never interact with it
        title = page.title()
        body = page.inner_text("body")[:3000] if page.query_selector("body") else ""
        server = (r.headers.get("server") if r else None) or ""
        cookie_names = sorted({c["name"] for c in ctx.cookies()})
        akamai = bool({"_abck", "bm_sz", "ak_bmsc"} & set(cookie_names)) or "akamai" in server.lower()
        # Not geo: a regular Chrome on the same IP gets the page (India gets a "proceed to the US site" modal,
        # not a 403; checked by hand 2026-11-10T22:2xZ). So a 403 here means the automated browser was refused.
        source = {"method": SOURCE, "url": page.url, "status": status}

        if (status and status in (401, 403, 429)) or BLOCK.search(title) or BLOCK.search(body[:1000]):
            ev.add("screenshot", "blocked.png", page.screenshot())
            ev.add("dom_text", "body.txt", body, excerpt=f"HTTP {status} {title!r}: {body[:200]}")
            ev.note("http_meta", json.dumps({"status": status, "server": server, "cookie_names": cookie_names,
                                             "final_url": page.url}))
            return Observation(product={"url": req.url}, source=source,
                               failure=(BOT_BLOCKED, {"status": status, "vendor": "akamai" if akamai else "unknown",
                                                      "page_title": title, "attempts": 1,
                                                      "suspected_cause": "automated browser refused (a regular "
                                                                         "Chrome on the same IP is served)",
                                                      "note": "one navigation, no retry, no evasion"}))

        # Rendered. Keep what an engineer needs to build the extraction, report nothing as a price.
        ld = [el.text_content() for el in page.query_selector_all('script[type="application/ld+json"]')]
        ev.add("screenshot", "page.png", page.screenshot())
        ev.add("embedded_json", "ld.json", json.dumps(ld, indent=1)[:200_000],
               excerpt=f"{len(ld)} JSON-LD blocks; title {title!r}")
        return Observation(product={"url": req.url, "title": title}, source=source,
                           failure=(SITE_ERROR, {"status": status, "note": "page rendered, but the West Elm price "
                                                 "extraction is not built: the rendered structure was never verified. "
                                                 "Evidence saved for adapter work; ops verifies by hand."}))
