# Suede price verification prototype

Checks the **current public US/USD unit price of one exact variant**, with evidence. When it can't establish the variant or the price, it returns **unresolved** with a reason, and it never guesses.

- [DESIGN.md](DESIGN.md): the architecture diagram (including the browser deep-dive) and design notes
- [ROADMAP.md](ROADMAP.md): what to build next. DESIGN notes + ROADMAP total ≤500 words.
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
| Nordic Knots | `custom/browser` | JSON-LD offers (**not yet verified live**, see limitations) | — |

## Example results
> **To fill in from the first live run.** Paste the JSON from `verify.py --input ../inputs.json`, with the run_id and the paths under `backend/evidence/<run_id>/`. Values seen in manual browser checks on 2026-11-10 (not a prototype run):
> - Serena & Lily Delancey Quilt Full/Queen Coastal Blue: **$268.00**, list $448.00, sitewide "Sale of the Year" banner with no code
> - King/Cal King Lark: $298 / $498
> - L&G Carson Sofa Ivory Modern Boucle 103"W: $2,598 in the *recorded* `.js` sample

**Failure → recovery demo (deliberately introduced):**
1. `--variant '{"Color": "Ivory Modern Boucle", "Size": "200\"W"}'` → `unresolved: variant_not_found` with the valid sizes listed. No default variant is substituted.
2. Correct it to `103"W` → `resolved`.

**Real failures observed:**
- Nordic Knots returned HTTP 200 with a `{"error":"Internal Server Error"}` body from India (Vercel edge `bom1`), in both curl and Chrome.
- Shopify returned `429 local_rate_limited` across five unrelated stores on their first request.

## Known limitations
- **Nordic Knots extraction is unverified.** It needs a US-egress run to pick a rug and pin the selectors. Today it detects the error body, retries twice, and returns `site_error` with evidence.
- **Geo:** we run from India. The adapters force US/USD (cookies and locale) and **verify** the applied market. A mismatch becomes `wrong_market`, never a converted guess.
- **Serena & Lily currency is inferred:** the site is US-only and `$`-formatted, with no currency field. This is recorded in `source.currency_basis`.
- **Headless Chromium may be bot-blocked** on some sites (Serena & Lily blocks curl). Fallbacks: `HEADLESS=0` / `BROWSER_CHANNEL=chrome`. In Docker only headless is possible.
- **Membership and promo detection** is a text heuristic on the page. It flags; it never changes the amount.
- **Cache TTL (15 min) and cooldown (120 s)** are hypotheses.
- Shipping and West Elm are deferred.

## Time spent
_TBD by the author._

## AI tools used and how the work was checked
- **Claude Code** (Claude Opus) for exploration, code and drafts.
- **Checks:**
  - Every page structure the adapters rely on was inspected live in Chrome first: the Serena & Lily embedded JSON, its price classes and its child ids.
  - Validation rules are covered by `test_validate.py`, running on a recorded Shopify payload.
  - Live results are compared against same-run screenshots and DOM text.
  - The README and notes separate manual observations from prototype runs.
