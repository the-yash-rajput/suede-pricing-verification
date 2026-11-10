-- Brands probed by hand on 2026-11-10 (see notes). The onboarding UI/probe adds more.
INSERT INTO brands (name, domain, approach, custom_method, adapter, ucp_endpoint, status, config) VALUES
  ('Lulu and Georgia', 'www.luluandgeorgia.com', 'shopify_ucp', NULL, 'shopify',
   'https://lulu-and-georgia.myshopify.com/api/ucp/mcp', 'live',
   '{"ttl_seconds": 900, "rate_scope": "shopify-global"}'),
  ('Serena & Lily', 'www.serenaandlily.com', 'custom', 'browser', 'serena_lily', NULL, 'live',
   '{"ttl_seconds": 900, "headed": true, "bot_vendor": "datadome"}'),
  ('Nordic Knots', 'www.nordicknots.com', 'custom', 'browser', 'nordic_knots', NULL, 'live',
   '{"ttl_seconds": 900}'),
  -- probe 2026-11-10T22:00Z: Akamai 403 "Restricted Access" on page, .js and /.well-known/ucp
  ('West Elm', 'www.westelm.com', 'custom', 'browser', 'west_elm', NULL, 'live',
   '{"ttl_seconds": 900, "headed": true, "bot_vendor": "akamai", "bot_cooldown_seconds": 21600}')
ON CONFLICT DO NOTHING;  -- name or domain already present
-- DataDome blocks headless Chromium on S&L (2026-11-11); existing DBs miss the seed change above.
UPDATE brands SET config = config || '{"headed": true, "bot_vendor": "datadome"}' WHERE name = 'Serena & Lily';
