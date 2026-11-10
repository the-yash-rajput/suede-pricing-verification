"""One place that opens a US-pinned Playwright browser. Adapters get a context; they never configure the browser."""
from __future__ import annotations

import os
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

HEADLESS = os.environ.get("HEADLESS", "1") != "0"
# Brands whose probe found a bot wall get config.headed=true -> headed even when HEADLESS=1 (Docker runs Xvfb).
CHANNEL = os.environ.get("BROWSER_CHANNEL") or None
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")


@contextmanager
def us_context(cookies: list[dict] | None = None, headed: bool = False):
    """en-US locale, New York timezone, optional market cookies. The egress IP is still wherever we run;
    adapters must read back the market/currency the site actually applied and validate() checks it."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS and not headed, channel=CHANNEL)
        ctx = browser.new_context(locale="en-US", timezone_id="America/New_York", user_agent=UA,
                                  viewport={"width": 1366, "height": 900})
        if cookies:
            ctx.add_cookies(cookies)
        try:
            yield ctx
        finally:
            ctx.close()
            browser.close()
