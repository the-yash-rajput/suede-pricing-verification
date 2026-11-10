"""HTTP API for the React UI. Thin: every price check goes through the same service.verify() as the CLI.

  uvicorn api:app --reload --port 8000
"""
import json
import os
import pkgutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import psycopg
from pydantic import BaseModel
from typing import Literal
from starlette.concurrency import run_in_threadpool

from pricecheck import brands as brand_pkg, db
from pricecheck.core import EVIDENCE_ROOT, Request, new_run_id
from pricecheck.probe import probe
from pricecheck.service import verify

INPUTS = Path(os.environ.get("INPUTS_FILE", Path(__file__).resolve().parent.parent / "inputs.json"))

app = FastAPI(title="Suede price verification")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])
EVIDENCE_ROOT.mkdir(exist_ok=True)
app.mount("/evidence", StaticFiles(directory=EVIDENCE_ROOT), name="evidence")


@app.on_event("startup")
def _init():
    db.init()


class VerifyIn(BaseModel):
    brand: str
    url: str
    variant: dict[str, str]
    quantity: int = 1
    no_cache: bool = False


class BrandIn(BaseModel):
    name: str
    domain: str
    sample_url: str


class BrandPatch(BaseModel):
    approach: str | None = None
    custom_method: str | None = None
    adapter: str | None = None
    status: Literal["live", "disabled"] | None = None
    config: dict | None = None


@app.post("/verify")
def post_verify(v: VerifyIn):
    # sync def -> FastAPI runs it in a worker thread; sync Playwright is fine there
    return verify(Request(v.brand, v.url, v.variant, v.quantity), no_cache=v.no_cache)


@app.post("/shipping")
def post_shipping(v: VerifyIn):
    """Optional extension: guest-cart shipping quote to New York, NY 10001, qty 1. Shopify brands only."""
    from pricecheck.shipping import quote
    brand = db.get_brand(v.brand)
    if not brand or brand["adapter"] != "shopify":
        raise HTTPException(422, "shipping quotes are only built for Shopify brands")
    return quote(Request(v.brand, v.url, v.variant, 1), brand, new_run_id())


@app.get("/inputs")
def get_inputs():
    return json.loads(INPUTS.read_text())


@app.post("/verify/inputs")
def verify_inputs(no_cache: bool = False):
    run_id = new_run_id()
    return [verify(Request(x["brand"], x["url"], x["variant"], x.get("quantity", 1)), no_cache=no_cache, run_id=run_id)
            for x in json.loads(INPUTS.read_text())]


@app.get("/observations")
def get_observations(brand: str | None = None, outcome: str | None = None, limit: int = 100):
    return db.list_observations(brand, outcome, limit)


@app.get("/brands")
def get_brands():
    return db.list_brands()


@app.post("/brands/probe")
async def post_probe(b: BrandIn):
    """Probe only; nothing saved. The UI shows this to ops before they save."""
    return await run_in_threadpool(probe, b.domain, b.sample_url)


def adapters() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(brand_pkg.__path__))


def _check_adapter(name: str | None):
    # adapter is fed to importlib in service.verify: only allow modules that exist in pricecheck/brands
    if name and name not in adapters():
        raise HTTPException(422, f"unknown adapter {name!r}; have {adapters()}")


@app.get("/adapters")
def get_adapters():
    return adapters()


@app.post("/brands")
def post_brand(b: dict):
    """Save a brand (usually the probe result, possibly overridden by ops)."""
    _check_adapter(b.get("adapter"))
    b["status"] = "live"  # saving is the end of onboarding; ops can disable it later
    try:
        return db.create_brand(b)
    except psycopg.errors.UniqueViolation:  # brands_name_ci_key / brands_domain_key in schema.sql
        raise HTTPException(409, f"a brand named {b.get('name')!r} or on {b.get('domain')!r} already exists")


@app.patch("/brands/{brand_id}")
def patch_brand(brand_id: int, p: BrandPatch):
    _check_adapter(p.adapter)
    row = db.update_brand(brand_id, p.model_dump(exclude_unset=True))
    if not row:
        raise HTTPException(404)
    return row
