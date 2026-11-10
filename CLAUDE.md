# Suede Take-Home: Public Pricing at Scale

Source: `~/Downloads/Agentic Commerce Take Home (1).pdf` (11 pages). This file is the working brief.
Project files:
- `notes`: working notes + live findings.
- `backend/`: Python/FastAPI/Playwright; `pricecheck/` has core + service + brands.
- `frontend/`: Vite React.
- `docker-compose.yml`.
- `inputs.json`.
- `DESIGN.md` + `ROADMAP.md`: ≤500 words combined.
- `README.md`.
- Recorded L&G sample: `backend/fixtures/carson-sofa.recorded.js`.
- Approved plan: `~/.claude/plans/lets-plan-how-we-twinkly-pumpkin.md`.

**Timebox: target 4h, hard stop at 6h, write-up included.** Pay: $150. Any language, libs, browser tools or AI tools are allowed.
Graded on **correctness, maintainability, judgment, handling uncertainty**. Extra features and production infra earn **no** extra credit.

## About Suede (from suedehome.com, read 2026-11-10)
- "The operating system for a new generation of designers." Aimed at emerging and independent interior designers (creators, junior designers, real-estate-adjacent people, "the design friend"). Membership costs $299/yr or $99/qtr and includes trade access, a branded site, invoicing, payments, AI sourcing search, a CRM and training.
- Flow: designer curates → client approves the proposal → client pays through **Suede's hosted checkout** → **Suede places the order** (it is buyer of record for trade purchases), tracks it and pays out the designer.
- 100+ brands. The homepage names CB2, Crate & Barrel, **West Elm**, DWR, **Lulu & Georgia**, Anthropologie, RH, Serena & Lily, Herman Miller, Arhaus, Soho Home, Jenni Kayne, Parachute, 1stDibs, **Nordic Knots**, House of Leon, Sabai, Sundays. Direct partners: House of Leon, Sabai, Italic.
- Two money models:
  - **Trade:** Suede buys at trade cost, "typically around 20% below retail." The designer sets the client price/markup. The spread is split 70/30 (designer/Suede).
  - **Affiliate:** the client buys from the vendor and Suede earns a commission (about 15%), which the vendor can reverse.
- Brand integration: "Shopify Collective or ERP" for direct partners, otherwise existing affiliate infrastructure. The site describes no price sync or refresh cadence.
- The Designer Terms push accuracy risk onto the designer ("solely responsible for… pricing inputs… and the accuracy of all information used to place orders"). They disclaim lead times, backorders and discontinued items. Trade pricing is confidential.

**Why accurate public price matters to Suede:**
- **Retail is the anchor.** Proposals quote retail-based prices and the margin is retail minus trade cost. If retail changes between proposal and checkout, the quote is wrong or the spread silently shrinks, and Suede, as buyer of record, absorbs the surprise.
- **Ops checks this by hand today.** The value of automation is fewer manual checks and fewer bad orders, measured against purchase volume.
- **Platforms split by brand group.** The named high-volume brands are mixed. Large retailers like West Elm (Williams-Sonoma), Crate & Barrel/CB2 and RH probably run custom enterprise stacks (unverified assumption), so "70% Shopify" may **not** hold by purchase volume. Verify this per brand. The top-12 allocation question turns on it.
- **Trade price is out of scope.** It needs logins. We verify only the **public retail** price, which Suede's trade math derives from.

## Business context
- Interior designers build proposals with products from many brands. A client may come back weeks later, after prices or purchase info have changed. A small ops team currently verifies this by hand before checkout.
- About **120 brands**. About **12 brands = 80% of purchase volume**.
- About **70% are on Shopify and support UCP** (capabilities vary by brand). The rest have inconsistent infrastructure.
- We may rethink when info is retrieved, cached, refreshed or reviewed manually.

## Scope
- In scope: **public retail price, U.S. storefront, USD.** Shipping is an optional extension.
- Out of scope: trade logins, customer accounts, membership pricing, negotiated quotes, tax, availability, lead times, checkout completion, payments.
- Results **inform** verification. They do **not** guarantee the final amount payable.

---

## Part 1: Recommend the system (~45–60 min)
Deliver **one architecture diagram** plus concise notes. No detailed infra design needed.
The diagram must show: **aging proposal → refreshed information → validation → usable result OR ops handoff → checkout readiness**.

Points to address:
- **Automate first where?** How to split effort between the top-12 brands and the long tail. Weigh purchase volume, running cost, ops effort, connector/automation maintenance and the value of more automation.
- **Where to use each method:** structured product data, direct integrations/APIs, browser automation, cache, human review. What is shared across brands and what stays brand-specific.
- **Fetch / cache / refresh / escalate:** when to do each. How validity changes when the product, variant, quantity or destination changes. Also concurrency, retries, rate limits and detecting retailer-site changes.
- **Trustworthiness:** what evidence goes with a result, when to return **unresolved** instead of guessing, how ops investigates an unresolved result, and what a success authorizes downstream versus what it does **not**.
- **Deep dive on one browser-dependent flow:** request → page/session → variant selection → extraction → validation → result, plus failure → retry or ops handoff. Cover how the product and variant are established, validation, retry behavior, retained evidence and what happens when the page structure changes. If a model directs browser actions: what it may do, what it may not do, and when it must stop or escalate.
- If the implementation changes the recommendation, **say what changed and why**.

## Part 2: Build the pricing prototype
- Brands: **Lulu and Georgia** and **Nordic Knots**. Pick one public product per brand and one **specific variant**. Prefer products whose variants have **different prices** so the right selection can be shown.
- Record for each: brand, product URL, selected variant, quantity 1. This is the **input file** and it gets submitted.
- **Shared entry point** with inputs: brand, product URL, variant, quantity. Returns the **current public unit price for the requested variant**.
- Must tell the current selling price apart from:
  - a crossed-out or original (compare-at) price
  - a membership-only price
  - a price that depends on a promo code
- **Never silently fall back to the default variant.** If the variant or price can't be established, return an explicit **unresolved** result with the reason and evidence.
- **Browser automation for at least one meaningful flow** (for example, selecting and validating the variant). Elsewhere: public APIs, structured page data, embedded JSON, browser network responses or other public structured sources. Choose the most maintainable and economical mix. (Shopify `/products/<handle>.js` / `.json` is the obvious candidate. Verify it per brand.)
- **Result fields (consistent schema):** brand, product, requested variant, market, currency, current amount (if known), price basis, source, observation time, outcome, supporting evidence.
- Keep **shared logic separate from brand-specific behavior**. Explain how a 3rd brand would be added and what stays bespoke. Don't implement it.
- A script, a small shared interface and local files are enough. **No generalized connector framework.**

## Part 3: Correctness and recovery
- Show both lookups with evidence (DOM text, screenshot, structured data, network response, etc.). Explain how the **exact variant** and the **current amount** were verified.
- **Demo one failure and recovery.** Example: an invalid variant fails (no substitution), then the variant is corrected and the rerun succeeds. **Clearly label** any failure introduced on purpose. Useful error output plus a rerun command is enough. No persistent workflow state or review UI is needed.
- **Live data:** record observation times and compare against evidence from the **same run**. If captured data is used to reproduce a failure, label it **recorded evidence**, not a current observation.

## Part 4: What to build next (design notes + roadmap, **≤ 500 words total**)
- Revisit the architecture in light of the prototype.
- **Scaling to 120 brands:** expanding coverage, what to standardize, what stays brand-specific, how to prioritize the top brands versus the long tail.
- **Reliability/ops metrics:** pricing correctness, coverage, % auto-resolved, latency, infra cost, maintenance burden, ops effort. What evidence is needed before letting more requests skip human review.
- **3-month roadmap** (1 engineer working with ops), month by month: ship / prioritize / test / evidence for expanding automation. The **first priority must tie to a real limitation or observation from the prototype.** Name at least **one deliberate deferral.** Treat all numeric targets as **hypotheses**, not Suede baselines.

## Optional (only after the required work, still inside 6h)
- **Shipping** (≤ 20–30 min): one selected product, **New York, NY 10001, US**, qty 1. Use a public calculator, a guest cart/checkout or a published policy. Report the amount, the service/method, per-item vs per-basket, and *policy-derived estimate* vs *checkout quote*. List any missing destination fields. No personal address, no account, no order. If unknown, return unresolved with the reason, evidence and the human action needed. **Unknown shipping is not $0.** A useful unresolved result fully satisfies this part.
- **West Elm** as a harder 3rd brand: public pricing plus CAPTCHA/bot-detection. Show what was retrieved, evidence of blockers, how retries are limited, when to hand off and how to resume. Unattended completion isn't required. Login is out of scope.

## Submission checklist
- [ ] Code: two-brand prototype + input file
- [ ] One diagram: architecture + the deeper browser flow
- [ ] Design + roadmap notes (≤ 500 words)
- [ ] README: setup/run, example results, evidence, known limitations, approximate time spent, AI tools used, how AI-assisted work was checked
- [ ] README/notes cite **at least one actual result** and **one observed limitation/failure** in the architecture or month-1 priorities
- No video or slides. If a site blocks progress, document the blocker and move on to independent work.

Follow-up for strong submissions: a 60-min working session (discussion, no live coding), so be ready to defend the choices.
