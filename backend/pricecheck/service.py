"""verify(): the one shared entry point. CLI, API and UI all call this.

brand lookup -> cache -> throttle -> adapter.fetch (with retries) -> validate -> save.
"""
from __future__ import annotations

import importlib
import json
import time
import traceback

from . import db
from .core import (NO_ADAPTER, RATE_LIMITED, SITE_ERROR, VARIANT_NOT_FOUND, Evidence, RateLimited, Request,
                   Transient, new_run_id, now_iso, unresolved, validate)

MAX_ATTEMPTS = 3          # 1 try + 2 retries, transient errors only
DEFAULT_TTL = 900         # ponytail: 15 min cache TTL is a hypothesis; per-brand override via brands.config.ttl_seconds
DEFAULT_COOLDOWN = 120    # after a 429 when the site gives no Retry-After


def cache_key(req: Request, market: str = "US") -> str:
    # quantity is not in the key: unit price; adapters assert no quantity breaks
    return json.dumps([req.brand.lower(), req.url.split("?")[0].rstrip("/").lower(),
                       sorted((k.lower(), v) for k, v in req.variant.items()), market])


def verify(req: Request, *, no_cache: bool = False, run_id: str | None = None) -> dict:
    run_id = run_id or new_run_id()
    if req.quantity < 1 or not req.variant:
        r = unresolved(req, VARIANT_NOT_FOUND, {"error": "variant options and quantity >= 1 are required"}, run_id)
        return _finish(req, r)

    brand = db.get_brand(req.brand)
    if not brand:
        return _finish(req, unresolved(req, NO_ADAPTER, {"error": f"brand '{req.brand}' is not onboarded"}, run_id))
    if not brand["adapter"] or brand["status"] == "disabled":
        return _finish(req, unresolved(req, NO_ADAPTER, {
            "error": "brand has no adapter yet (custom approach) or is disabled; ops must verify manually",
            "approach": brand["approach"], "custom_method": brand["custom_method"], "status": brand["status"]},
            run_id))

    cfg = brand["config"] or {}
    key = cache_key(req)
    if not no_cache:
        hit = db.get_cached(key, cfg.get("ttl_seconds", DEFAULT_TTL))
        if hit:
            hit["outcome"]["from_cache"] = True           # observation_time stays the original read time
            hit["outcome"]["served_in_run"] = run_id
            return hit

    scope = cfg.get("rate_scope") or f"domain:{brand['domain']}"
    wait = db.cooldown_remaining(scope)
    if wait:
        return _finish(req, unresolved(req, RATE_LIMITED, {"scope": scope, "retry_after_seconds": wait,
                                                           "note": "cooldown active from an earlier 429"}, run_id))

    adapter = importlib.import_module(f"pricecheck.brands.{brand['adapter']}")
    ev = Evidence(run_id, req.brand)
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            observed_at = now_iso()
            obs = adapter.fetch(req, brand, ev)
            obs.evidence = ev.items
            obs.source.setdefault("attempts", attempt)
            return _finish(req, validate(req, obs, run_id, observed_at), key)
        except RateLimited as e:
            db.set_cooldown(e.scope, e.retry_after, "429")
            return _finish(req, unresolved(req, RATE_LIMITED, {"scope": e.scope, "retry_after_seconds": e.retry_after},
                                           run_id, ev.items), key)
        except Transient as e:
            last_err = str(e)
            ev.note("retry", f"attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)                     # 2s, 4s
        except Exception as e:                           # adapter bug / page changed: never guess, hand off
            ev.note("error", "".join(traceback.format_exception_only(e)).strip())
            return _finish(req, unresolved(req, SITE_ERROR, {"error": repr(e), "hint": "adapter crashed; page "
                                           "structure may have changed"}, run_id, ev.items), key)
    return _finish(req, unresolved(req, SITE_ERROR, {"error": last_err, "attempts": MAX_ATTEMPTS},
                                   run_id, ev.items), key)


def _finish(req: Request, r: dict, key: str | None = None) -> dict:
    db.save(key or cache_key(req), r)
    return r
