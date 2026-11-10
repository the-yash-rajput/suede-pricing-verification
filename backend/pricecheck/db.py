"""Postgres helpers. Plain SQL, no ORM."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///suede_pricing")


def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def init():
    with connect() as c:
        c.execute((ROOT / "schema.sql").read_text())
        c.execute((ROOT / "seed.sql").read_text())


# --- brands ---
def get_brand(name: str) -> dict | None:
    with connect() as c:
        return c.execute("SELECT * FROM brands WHERE lower(name) = lower(%s)", (name,)).fetchone()


def list_brands() -> list[dict]:
    with connect() as c:
        return c.execute("SELECT * FROM brands ORDER BY id").fetchall()


BRAND_FIELDS = ("name", "domain", "approach", "custom_method", "adapter", "ucp_endpoint",
                "ucp_capabilities", "probe_evidence", "status", "config")
JSON_FIELDS = {"ucp_capabilities", "probe_evidence", "config"}


def _vals(d: dict) -> dict:
    return {k: (Jsonb(v) if k in JSON_FIELDS and v is not None else v) for k, v in d.items() if k in BRAND_FIELDS}


def create_brand(d: dict) -> dict:
    v = _vals(d)
    cols = ", ".join(v)
    with connect() as c:
        return c.execute(f"INSERT INTO brands ({cols}) VALUES ({', '.join('%(' + k + ')s' for k in v)}) RETURNING *",
                         v).fetchone()


def update_brand(brand_id: int, d: dict) -> dict | None:
    v = _vals(d)
    if not v:
        with connect() as c:
            return c.execute("SELECT * FROM brands WHERE id = %s", (brand_id,)).fetchone()
    sets = ", ".join(f"{k} = %({k})s" for k in v)
    with connect() as c:
        return c.execute(f"UPDATE brands SET {sets}, updated_at = now() WHERE id = %(id)s RETURNING *",
                         {**v, "id": brand_id}).fetchone()


# --- cache / observations ---
def get_cached(cache_key: str, ttl_seconds: int) -> dict | None:
    """Latest RESOLVED observation younger than ttl. Unresolved results are never served from cache."""
    with connect() as c:
        row = c.execute(
            "SELECT result FROM observations WHERE cache_key = %s AND outcome = 'resolved' "
            "AND observed_at > now() - make_interval(secs => %s) ORDER BY observed_at DESC LIMIT 1",
            (cache_key, ttl_seconds)).fetchone()
    return row["result"] if row else None


def save(cache_key: str, r: dict):
    amt = r["current_amount"]
    with connect() as c:
        c.execute(
            "INSERT INTO observations (run_id, cache_key, brand, product_url, requested_variant, resolved_variant_id,"
            " qty, outcome, reason, amount_cents, currency, market, price_basis, source, observed_at, result)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (r["outcome"]["run_id"], cache_key, r["brand"], r["product"].get("url"),
             Jsonb(r["requested_variant"]["options"]), r["requested_variant"].get("resolved_variant_id"),
             r["requested_variant"]["quantity"], r["outcome"]["status"], r["outcome"]["reason"],
             None if amt is None else int(Decimal(amt) * 100), r["currency"], r["market"],
             r["price_basis"]["type"], r["source"].get("method"), r["observation_time"],
             Jsonb(json.loads(json.dumps(r, default=str)))))


def list_observations(brand: str | None = None, outcome: str | None = None, limit: int = 100) -> list[dict]:
    q, args = "SELECT id, result FROM observations WHERE true", []
    if brand:
        q += " AND lower(brand) = lower(%s)"; args.append(brand)
    if outcome:
        q += " AND outcome = %s"; args.append(outcome)
    q += " ORDER BY id DESC LIMIT %s"; args.append(limit)
    with connect() as c:
        return [r["result"] | {"_id": r["id"]} for r in c.execute(q, args).fetchall()]


# --- throttle ---
def cooldown_remaining(scope: str) -> int:
    with connect() as c:
        row = c.execute("SELECT cooldown_until FROM throttle WHERE scope = %s", (scope,)).fetchone()
    if not row:
        return 0
    return max(0, int((row["cooldown_until"] - datetime.now(timezone.utc)).total_seconds()))


def cooldown_status(scope: str) -> str | None:
    """Why the scope is cooling down: '429' (rate limit) or 'bot_blocked' (brand paused)."""
    with connect() as c:
        row = c.execute("SELECT last_status FROM throttle WHERE scope = %s", (scope,)).fetchone()
    return row["last_status"] if row else None


def set_cooldown(scope: str, seconds: int, status: str):
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    with connect() as c:
        c.execute("INSERT INTO throttle (scope, cooldown_until, last_status) VALUES (%s,%s,%s) "
                  "ON CONFLICT (scope) DO UPDATE SET cooldown_until = EXCLUDED.cooldown_until, "
                  "last_status = EXCLUDED.last_status", (scope, until, status))
