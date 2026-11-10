-- Brands probed by hand on 2026-11-10 (see notes). The onboarding UI/probe adds more.
INSERT INTO brands (name, domain, approach, custom_method, adapter, ucp_endpoint, status, config) VALUES
  ('Lulu and Georgia', 'www.luluandgeorgia.com', 'shopify_ucp', NULL, 'shopify',
   'https://lulu-and-georgia.myshopify.com/api/ucp/mcp', 'live',
   '{"ttl_seconds": 900, "rate_scope": "shopify-global"}'),
  ('Serena & Lily', 'www.serenaandlily.com', 'custom', 'browser', 'serena_lily', NULL, 'live',
   '{"ttl_seconds": 900}'),
  ('Nordic Knots', 'www.nordicknots.com', 'custom', 'browser', 'nordic_knots', NULL, 'live',
   '{"ttl_seconds": 900}')
ON CONFLICT (name) DO NOTHING;
