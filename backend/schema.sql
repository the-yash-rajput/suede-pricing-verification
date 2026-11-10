-- Idempotent: safe to run on every start.
CREATE TABLE IF NOT EXISTS brands (
    id              serial PRIMARY KEY,
    name            text UNIQUE NOT NULL,
    domain          text NOT NULL,
    approach        text NOT NULL CHECK (approach IN ('shopify_ucp', 'shopify', 'custom')),
    custom_method   text CHECK (custom_method IN ('page_structured', 'site_api', 'browser', 'manual')),
    adapter         text,                 -- module in pricecheck/brands; NULL = not built yet -> unresolved: no_adapter
    ucp_endpoint    text,
    ucp_capabilities jsonb,
    probe_evidence  jsonb,
    status          text NOT NULL DEFAULT 'onboarding' CHECK (status IN ('onboarding', 'live', 'disabled')),
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- ttl_seconds, rate_scope, extra banner phrases
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observations (
    id                  bigserial PRIMARY KEY,
    run_id              text NOT NULL,
    cache_key           text NOT NULL,
    brand               text NOT NULL,
    product_url         text NOT NULL,
    requested_variant   jsonb NOT NULL,
    resolved_variant_id text,
    qty                 int NOT NULL,
    outcome             text NOT NULL,
    reason              text,
    amount_cents        bigint,
    currency            text,
    market              text,
    price_basis         text,
    source              text,
    observed_at         timestamptz NOT NULL,
    result              jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_cache_idx ON observations (cache_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS observations_brand_idx ON observations (brand, observed_at DESC);

CREATE TABLE IF NOT EXISTS throttle (
    scope           text PRIMARY KEY,     -- e.g. 'shopify-global' (Shopify throttles per client IP across stores)
    cooldown_until  timestamptz NOT NULL,
    last_status     text
);
