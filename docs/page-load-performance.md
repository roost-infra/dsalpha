# Page-load performance and Cloudflare edge cache

Measured from the Hong Kong edge on 2026-11-23, while the app was live at
`https://dsalpha.roostbots.com`:

| Request | Result |
|---|---|
| `/chat` HTML | `cf-cache-status: DYNAMIC`, `cache-control: no-cache`, TTFB ~1.4s |
| `/dashboard` HTML | `cf-cache-status: DYNAMIC`, `cache-control: no-cache`, TTFB ~1.4s |
| `/` landing HTML | `cf-cache-status: DYNAMIC`, `cache-control: no-cache`, TTFB ~1.6s |
| `/assets/index-*.js` | `cf-cache-status: HIT` after first request, `content-encoding: br`, ~253KB |
| `/assets/vendor-react-*.js` | `HIT`, `br`, ~82KB |
| `/assets/index-*.css` | `HIT`, `br`, ~28KB |
| `/landing/styles.css` | `REVALIDATED`, `max-age=14400` |

Cloudflare is already proxying the app (`server: cloudflare`), compressing with
Brotli, and caching the fingerprint assets. The two things it is not doing are
HTML edge caching and a deploy-driven purge.

## Required Cloudflare Cache Rule

Create one Cache Rule for the zone (dashboard: Caching → Cache Rules):

**Name:** `dsalpha SPA shell`

**Expression:**

```text
(http.host eq "dsalpha.roostbots.com" and not starts_with(http.request.uri.path, "/api/") and not starts_with(http.request.uri.path, "/ws/") and not starts_with(http.request.uri.path, "/assets/") and not starts_with(http.request.uri.path, "/landing/") and not starts_with(http.request.uri.path, "/sb/"))
```

**Settings:**

- Cache eligibility: **Eligible for cache**
- Edge TTL: **Override origin**, 300 seconds
- Browser TTL: **Bypass cache** (the HTML shell should revalidate; assets carry their own immutable headers)
- Cache key: default (host + path + query)

The app shell is the same document for every signed-in user; user data is
fetched by the client. Do not include `/api/`, `/ws/`, `/sb/` or any
`Set-Cookie` response in this rule.

A second rule is optional for `/landing/`: keep the current short TTL (4h or
less) because `landing/styles.css` and `landing/landing.js` are not
fingerprinted.

## Deploy purge

`deploy-web.yml` now purges the edge after a successful deploy when these
repository secrets exist:

- `CLOUDFLARE_ZONE_ID`
- `CLOUDFLARE_API_TOKEN` with **Zone → Cache Purge → Purge** permission

Without both secrets the step prints a skip message and does nothing. With
HTML edge caching enabled, the purge is what keeps a deploy from serving the
previous shell and its dead asset hashes.

## What not to enable

- **Rocket Loader**: it changes script execution for a module SPA and can break
  the entry/stale-build recovery.
- **Cache Everything on `/api/`**: responses are user-scoped.
- **Long browser cache on the HTML shell**: the shell contains hashed asset
  references and must be allowed to revalidate after a deploy.

## Next bundle work

The initial wire is roughly 363KB compressed (index ~253KB br + React ~82KB +
CSS ~28KB). Cloudflare can deliver it faster but cannot make it smaller.
`scripts/check-critical-path.mjs` and the `$initial` chunk rule already keep
lazy vendors off the first load; the next step is a bundle report on the app
entry and moving remaining eager panels behind route/panel boundaries.

Enable Cloudflare Web Analytics / RUM before changing bundle boundaries so the
p75 TTFB, LCP and INP changes can be measured rather than guessed.
