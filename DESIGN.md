# Design: keeping public product info accurate across ~120 brands

```mermaid
flowchart TD
  A[Aging proposal line<br/>brand · URL · variant options · qty] --> T{Trigger}
  T -->|line added · client reopens · TTL expired · scheduled sweep| C{Fresh cached<br/>resolved result?}
  T -->|checkout| F
  C -->|yes, within brand TTL| U
  C -->|no| B[(brands table<br/>approach · adapter · status)]
  B -->|no adapter / disabled| H
  B --> R{Shared rate budget<br/>cooling down?}
  R -->|yes| H
  R -->|no| F[Refresh via brand approach]
  F --> S1[Shopify / UCP: product JSON<br/>+ browser cross-check]
  F --> S2[Custom: page JSON → site API → browser]
  S1 --> V
  S2 --> V
  V{validate: exact variant · single price ·<br/>basis · US/USD · sources agree}
  V -->|pass| U[Usable result + evidence]
  V -->|fail| H[Unresolved: reason + evidence → ops queue]
  H -->|ops resolves, labels case → fixture| U
  U --> K[Checkout ready: every line resolved<br/>within window, or ops sign-off]

  subgraph BR [Browser-dependent flow · Serena & Lily]
    direction LR
    b1[Request] --> b2[US-pinned page] --> b3[Read embedded product JSON]
    b3 --> b4[Map options → child id<br/>none → unresolved]
    b4 --> b5[Navigate to child,<br/>RE-READ selected options]
    b5 --> b6[Extract sale/list cents<br/>+ rendered DOM price]
    b6 --> b7[validate]
    b2 -.->|5xx / error body / timeout| r1[Retry ×2, backoff] -.->|still failing| r2[Ops handoff + screenshots]
    b3 -.->|JSON/selector missing = page changed| r2
  end
  S2 -.-> BR
```

## Notes

**Automate first:** the top 12 brands (80% of volume), whatever their platform. Shopify brands, about 70% of brands, onboard through one generic adapter with config only, which covers the long tail cheaply. Non-Shopify long-tail brands stay manual until their ops cost justifies an adapter.

**Method choice** goes cheapest-first: structured JSON or UCP → site API → browser (cross-checks, sites that block HTTP) → human. Shared: validation, result format, evidence, cache, throttle, probe. Bespoke: variant mapping, selectors, banner meaning.

**Refresh rules:**
- Always fetch fresh before checkout.
- Reuse a cached result within a per-brand TTL.
- A product or variant change invalidates the result.
- A quantity change reuses the unit price, but re-checks quantity breaks.
- Destination matters only for shipping.

**Rate limits and retries:** Shopify throttled us per IP *across stores*, so there is one shared budget with a cooldown. Retry transient errors at most twice; never retry a mismatch.

**Trust:** every result carries source, payload hash, screenshot and observation time. Unresolved when the variant isn't exact, only a range shows, the currency isn't USD, only a conditional price exists, or sources disagree. A resolved result authorizes showing the price and treating the line as verified for the checkout window. It does not authorize a final payable amount or placing an order.

**Models:** there is no LLM in the runtime path. A future model may navigate and click options. It may never type codes, log in, or choose the price, and it must stop on a CAPTCHA or an ambiguous variant.
