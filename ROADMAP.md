# What I'd build next

**What the prototype changed:** Nordic Knots and Serena & Lily are both headless Next.js, not Shopify, and Serena & Lily blocks plain HTTP. Shopify rate-limited us (`429`) across *unrelated* stores on the first request, so the shared budget and the cache matter more than I first assumed.

**Scaling:** probe every brand, onboard Shopify brands with config only, and write adapters for the non-Shopify top-12 brands.

**Metrics** (targets are hypotheses, not baselines):
- correctness against ops-labelled checks
- coverage of proposal lines
- % auto-resolved
- p95 latency per method
- cost per check
- adapter breakages per month
- ops minutes per unresolved

**Before a brand skips human review:** shadow agreement with ops over a sample that includes sales and unavailable variants, plus zero wrong-variant results.

| Month | Ship | Test | Evidence to expand |
|---|---|---|---|
| 1 | Shared Shopify budget, cache, mandatory pre-checkout refresh (from the observed 429); all Shopify brands in shadow mode | Ops ground truth per brand | Agreement holds across sale events |
| 2 | Custom adapters for the top-12 non-Shopify brands; site-change detection and auto-demote | Spot-check the browser path against cheap sources | Low breakage rate |
| 3 | Sweep of open proposals; ops queue; shipping as a new check type | Cost per check | Ops minutes falling |

**Deferred:** West Elm and bot-protected sites, and LLM-directed browsing, until the cheaper paths are saturated.

**After month 3:**
- UCP `catalog.lookup` as the fallback when `.js` is rate-limited, and as a second source to cross-check against.
- CAPTCHA/bot-wall handling for sites like Serena & Lily: a solver service, only where the brand's terms allow it.
- Model-directed browsing (e.g. Browser Use) for flows Playwright can't settle. It may select variants and read prices; it stops and hands off to ops on any login, checkout or uncertain match.
- Auth (ops/admin roles) and an admin panel for brands, adapters and limits.
- Separate backend and frontend repos; UI polish.
