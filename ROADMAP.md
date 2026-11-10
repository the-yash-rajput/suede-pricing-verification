# What I'd build next

**What the prototype changed:** Nordic Knots and Serena & Lily are headless Next.js, not Shopify, and Serena & Lily blocks plain HTTP. Shopify rate-limited us (`429`) across *unrelated* stores on the first request, so the shared budget and the cache matter more than I first assumed. `shopify_ucp` is only a label today: UCP isn't used yet.

**Approach:** expand coverage through standard integrations, adapters chosen by volume, and model-driven browsing as an experiment. Accuracy and ops effort come before raw coverage.

## Scaling to 120 brands
- **Standardize:** the Shopify adapter, UCP discovery, variant matching, pricing rules, evidence, the result format, rate limits, and the onboarding probe.
- **Brand-specific:** selectors, variant mapping, site APIs, market/session handling.
- **Top 12 (80% of volume):** dedicated adapters, ordered by purchase volume × current ops minutes.
- **Long tail:** the generic Shopify adapter where possible; otherwise ops, plus the browsing pilot.

## Metrics (targets set from month-1 data; none are Suede baselines)
- Correctness against ops-labelled checks.
- Coverage of proposal lines and % auto-resolved.
- p95 latency and cost per check.
- Adapter breakages per month and ops minutes per unresolved.

**A brand skips ops review only after** shadow agreement with ops over a sample that includes sales and unavailable variants, with zero wrong-variant results.

## 3 months
| Month | Ship | Evidence to expand |
|---|---|---|
| 1 | Probe all 120 brands and weight the results by volume (does "70% Shopify" hold for the top 12?). UCP `catalog.lookup` as a fallback and cross-check for `.js` (from the 429). Request scheduling and dedup of simultaneous checks inside the shared Shopify budget. Fresh check required before checkout. Everything in shadow mode against ops. | Agreement holds across sale events |
| 2 | Adapters for the non-Shopify top 12. Site-change detection that sends a breaking brand back to ops. An ops queue (unresolved results, evidence, resolve/label, brand config) with ops/admin roles. | Low breakage, fewer ops minutes |
| 3 | Browser Use pilot on long-tail browser brands, shadow only: no login, no codes, no CAPTCHA bypass. Promote brands that pass. Proven brands skip routine ops review. | Agreement under the same gate |

**Deferred:**
- CAPTCHA-solving services, because of terms-of-service, reliability and brand-relationship risk. Use affiliate feeds, Shopify Collective or partner integrations instead.
- Separate repos and standalone UI polish.
