# Suede price verification prototype

Checks the **current public US/USD unit price of one exact variant**, with evidence. When it can't establish the variant or the price, it returns **unresolved** with a reason, and it never guesses.

- [DESIGN.md](DESIGN.md): the architecture diagram (including the browser deep-dive) and design notes
- [ROADMAP.md](ROADMAP.md): what to build next. DESIGN notes + ROADMAP total ≤500 words.
  - **Month 1:** probe all 120 brands by volume; UCP fallback (from the observed 429); a shared Shopify request schedule; a fresh check before checkout; shadow mode.
  - **Month 2:** adapters for the non-Shopify top 12; site-change detection; an ops queue with roles.
  - **Month 3:** a shadow pilot of model-driven browsing on the long tail; proven brands skip ops review.
  - **Deferred:** CAPTCHA solving.
- [inputs.json](inputs.json): the chosen products and variants (quantity 1)

```
backend/   Python 3.13 · Playwright · FastAPI · Postgres (psycopg)
  pricecheck/core.py        shared: types, validate(), evidence        (no brand code)
  pricecheck/service.py     verify(): brand lookup → cache → throttle → adapter → validate → save
  pricecheck/brands/        shopify.py (generic, any Shopify brand) · serena_lily.py · nordic_knots.py
  pricecheck/probe.py       onboarding probe → proposed approach
  verify.py  api.py  schema.sql  seed.sql  test_validate.py  fixtures/
frontend/  Vite + React: Verify · Brands (onboarding) · Observations (ops queue)
docker-compose.yml          db + backend + frontend
```

## Run

**Docker (everything):**
```bash
colima start                     # or Docker Desktop
docker-compose up --build        # UI http://localhost:5173 · API http://localhost:8000/docs
docker-compose exec backend python test_validate.py
docker-compose exec backend python verify.py --input   # bare --input = the mounted inputs.json
```
The images install everything (Chromium, Python deps, npm), so no local setup is needed for Docker.

**Avoiding reinstalls:**
- **Installs are cached layers.** pip and `npm install` re-run only when `backend/pyproject.toml` or `frontend/package.json` / `package-lock.json` change.
- **Code is mounted.** `./backend` runs with `uvicorn --reload` and `./frontend` with Vite hot reload, so editing code never needs a rebuild.
- **Daily use:** `docker-compose up -d`, without `--build`. Use `--build` only after changing dependencies.
- **What wipes it:**
  - `docker system prune -a` / `docker builder prune` delete the cached layers, so everything downloads again.
  - `docker-compose down -v` also deletes the Postgres data.
  - Plain `docker-compose down` keeps both.

**Local:**
```bash
createdb suede_pricing                                   # or set DATABASE_URL
cd backend && uv sync && uv run playwright install chromium
uv run python test_validate.py                           # rules on recorded data, no network
uv run python verify.py --input ../inputs.json           # all lines; exit 2 if any unresolved
uv run uvicorn api:app --port 8000                       # API for the UI
cd ../frontend && npm install && npm run dev             # UI on :5173
```

**One line, with a rerun command:**
```bash
uv run python verify.py --brand "Lulu and Georgia" \
  --url https://www.luluandgeorgia.com/products/carson-sofa \
  --variant '{"Color": "Ivory Modern Boucle", "Size": "103\"W"}' --qty 1 --no-cache
```
Unresolved lines print a ready-made rerun command on stderr. In the UI, every result has **Rerun**, **Rerun fresh** and **Edit & rerun**.

Env vars:
- `DATABASE_URL` (default `postgresql:///suede_pricing`)
- `HEADLESS=0` to watch the browser
- `BROWSER_CHANNEL=chrome` to use installed Chrome

## Result format
Every result has exactly the brief's 11 top-level fields, in this order:

`brand, product, requested_variant, market, currency, current_amount, price_basis, source, observation_time, outcome, supporting_evidence`

- **`current_amount`** is always the current public selling price, as a decimal string, or `null`. It is never `0`.
- **Crossed-out / original price** goes in `price_basis.compare_at_amount`. It's only set when it's above the selling price.
- **Membership, promo-code and financing prices** go in `price_basis.conditions[]`. They never go in `current_amount`.
- **`outcome.reason`** is set when the result is unresolved. Possible values:
  - `variant_not_found`, `variant_unavailable`
  - `range_only`, `price_not_found`, `conditional_price_only`
  - `wrong_market`, `sources_disagree`
  - `site_error`, `rate_limited`, `no_adapter`
- **`observation_time`** is when the source was read. A cache hit keeps the original time and sets `from_cache: true`.
- **Recorded evidence** (saved data, not a live observation) is marked `recorded: true`.

## How each brand is verified
| Brand | Approach | Variant established by | Amount verified by |
|---|---|---|---|
| Lulu and Georgia | `shopify_ucp`: generic adapter, config only | exact option match in `/products/<handle>.js` → variant id; the page opened at `?variant=<id>` must select the same id | JSON price (cents) must equal the rendered page price; `Shopify.currency.active`/`Shopify.country` must be USD/US |
| Serena & Lily | `custom/browser` (curl 403, browser OK) | options → child product id from the page's embedded JSON; navigate there and **re-read** the selected options | embedded sale/list cents must equal the rendered sale price; "Save X%" list price → compare-at; Affirm $/mo ignored |
| West Elm (optional) | `custom/browser`, headed, Akamai | not reached: blocked on the first navigation | not reached: returns `bot_blocked` with evidence and pauses the brand (see below) |
| Nordic Knots | `custom/browser` (Next.js + Centra cart) | JSON-LD offer by exact `size`; if the page shows another size, pick it in the size listbox and **re-read** the picker + URL | JSON-LD amount must equal the rendered `[aria-live]` price; currency/market come from the **Centra session** (`/api/checkout/selection`), not the `/us` path |

## Example results
> **To fill in from the first live run.** Paste the JSON from `verify.py --input ../inputs.json`, with the run_id and the paths under `backend/evidence/<run_id>/`. Values seen in manual browser checks on 2026-11-10 (not a prototype run):
> - Serena & Lily Delancey Quilt Full/Queen Coastal Blue: **$268.00**, list $448.00, sitewide "Sale of the Year" banner with no code
> - King/Cal King Lark: $298 / $498
> - L&G Carson Sofa Ivory Modern Boucle 103"W: $2,598 in the *recorded* `.js` sample

**Failure → recovery demo (deliberately introduced):**
1. `--variant '{"Color": "Ivory Modern Boucle", "Size": "200\"W"}'` → `unresolved: variant_not_found` with the valid sizes listed. No default variant is substituted.
2. Correct it to `103"W` → `resolved`.

**Real failures observed:**
- Nordic Knots returned HTTP 200 with a `{"error":"Internal Server Error"}` body from India (Vercel edge `bom1`), in both curl and Chrome (2026-11-10). By 2026-11-11 the pages loaded.
- **Nordic Knots, Grand – Milano Green 5'x8' (2026-11-11, run `r-20261110T212239Z-4f9dee`):** JSON-LD says `995 USD`, sku `GRAN-MGR-58-R`, but the page renders **`995 CHF`**. The Centra session is `country=SG, pricelist=31, currency=CHF` (our egress geolocates to Singapore; `vercelIpCountry=SG`). Result: `unresolved: wrong_market`, not a guessed $995. The JSON-LD "USD" follows the `/us` path, not the shopper's market. `NEXT_COUNTRY=US`, `?country=us` and the path don't change Centra, and the site has no country selector.
- Shopify returned `429 local_rate_limited` across five unrelated stores on their first request.

## Known limitations
- **Nordic Knots resolves only from a US egress.** The extraction and variant selection are verified live. The market check correctly refuses the SG/CHF session we get from here. A US VPN or a US-hosted worker should turn the same run into `resolved` USD 995.00 (unverified until then).
- **Geo:** we run from India. The adapters force US/USD (cookies and locale) and **verify** the applied market. A mismatch becomes `wrong_market`, never a converted guess.
- **Serena & Lily currency is inferred:** the site is US-only and `$`-formatted, with no currency field. This is recorded in `source.currency_basis`.
- **Serena & Lily is behind DataDome** (curl 403 page from `geo.captcha-delivery.com`). The onboarding probe now names the vendor and proposes `config.headed=true`. Brands with that flag launch headed Chromium, on an Xvfb screen (`:99`) in Docker. Other brands stay headless.
  Observed 2026-11-11 (run `r-20261110T203840Z-2e19ea`): headed Chromium on Xvfb was **still blocked**. DataDome's page names our IP ("uncommon activity… IP 157.49.55.86") after the earlier runs, so it is an IP flag, not a headless fingerprint. The result is `unresolved: bot_blocked` after **one** attempt, with `blocked.png` and the body as evidence. Ops checks the price by hand and re-runs after the flag clears. No evasion.
- **Membership and promo detection** is a text heuristic on the page. It flags; it never changes the amount.
- **Cache TTL (15 min) and cooldown (120 s)** are hypotheses.
- Shipping is deferred. West Elm is attempted, but blocked from our egress (see below).

## West Elm (optional harder brand)
Live, 2026-11-10 22:00–22:08 UTC, from India. Product: Pre-Lit Faux Citrus Garland, `https://www.westelm.com/products/citrus-garland-d18933/`, requested `Size: 8'`.

- **What was retrieved, by a manual check in a regular Chrome (not a prototype run):**
  - Size 5' is **$129** and 8' is **$159**, read from the rendered price after selecting each size.
  - The JSON-LD `AggregateOffer` is USD, with offer SKUs 9321690 ($129) and 7423483 ($159). The offers carry no size names, so the size-to-SKU link comes from the price.
  - India visitors get a "proceed to the US site" popup, not a 403.
- **What the prototype retrieved:** nothing about the product. The onboarding probe (plain HTTP) got **403 "West Elm: 403 - Restricted Access"** with `server: AkamaiNetStorage` on the page, `/products/<handle>.js` and `/.well-known/ucp`. It proposed `custom/browser`, `headed=true`, `bot_vendor=akamai`.
- **Blocker evidence:**
  - Run `r-20261110T220718Z-15527b`, one headed Chromium navigation to the garland URL. It got the same 403 page ("due to website restrictions we are unable to display the requested page"). Evidence is `blocked.png`, `body.txt` and the cookie names.
  - A regular Chrome on the **same IP** is served, so this is the automated browser being refused, not a country block.
  - Correction: earlier runs (`r-20261110T2201…`, `…2202…`) used a product URL I guessed, which redirects to the homepage in a real browser. I first misread those runs as a geo block.
- **How retries are limited:**
  - A block costs exactly **one** navigation: `bot_blocked` is not a retryable error.
  - `service.verify` then **pauses the brand** for 6h (a hypothesis; per brand via `config.bot_cooldown_seconds`), using the same `throttle` table as 429 cooldowns.
  - Run `r-20261110T220223Z-3f5a42` (guessed URL; the pause is per domain, so that doesn't matter here) shows the next request returning `bot_blocked: brand paused…; site NOT contacted`, with `retry_after_seconds`.
- **Handoff:** the result's `handoff` tells ops to open the URL in a normal browser, select the variant, and record the price and a screenshot against the run_id. The UI shows this as "Ops action".
- **Resume:**
  - The pause ends on its own, or ops ends it early with `DELETE FROM throttle WHERE scope = 'domain:www.westelm.com'` and reruns with `--no-cache`.
  - Run `r-20261110T220233Z-34cc0d` shows this: the site was contacted again, blocked again, and paused again.
  - The durable fix is a sanctioned source: a brand catalog feed, an affiliate API, or allowlisting.
- **Deliberately not done:** no CAPTCHA solving, no proxy rotation, no fingerprint evasion. The brief says unattended completion isn't required, and as buyer of record Suede shouldn't depend on circumventing a retailer's bot protection.
- **Not built:** the price extraction, because the prototype never saw the page. The manual check shows what it would be: JSON-LD offer by SKU, then select the size, re-read "Select Size", and cross-check the rendered price. If the page ever renders for the prototype, the adapter saves the JSON-LD and a screenshot and returns `site_error` ("extraction not built"). It never guesses a price.

## Time spent
_TBD by the author._

## AI tools used and how the work was checked
- **Claude Code** (Claude Opus) for exploration, code and drafts.
- **Checks:**
  - Every page structure the adapters rely on was inspected live in Chrome first: the Serena & Lily embedded JSON, its price classes and its child ids.
  - Validation rules are covered by `test_validate.py`, running on a recorded Shopify payload.
  - Live results are compared against same-run screenshots and DOM text.
  - The README and notes separate manual observations from prototype runs.
