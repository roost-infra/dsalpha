# Roost Billing (dslpha)

dslpha can use the Roost Console as its quota service instead of the legacy
`quota-service`. No product-side lease code changes beyond configuration:
the existing `PlatformCreditGatePort` talks to the compatibility routes.

## Environment

```bash
AUTH_SERVICE_URL=https://www.roostbots.com/console-api
INTERNAL_SERVICE_TOKEN=<Roost API SERVICE_SECRET>
USD_TO_CREDITS_RATE=720     # 1 USD ≈ 720 Roost credits (100 credits = ¥1)
```

`HOST_MODE=platform` must be set as usual.

## Compatibility surface

Roost exposes the same paths the legacy quota service used:

```text
POST /api/auth/validate
POST /api/auth/billing/leases/acquire
POST /api/auth/billing/leases/release
GET  /api/auth/billing/leases/capability
```

The release payload includes `spent_credits`, read from the run's own
`in_flight_credits` heartbeat, so the turn is settled against the organization
wallet exactly once. A failed release leaves the lease to expire; the expiry
worker releases the reservation.

## Account mapping

The bridge maps a Supabase `user_id` to a Roost organization on first use. If
the user has no organization yet, a personal `Roost Demo`-style org is created
with the Free plan and 1,000 credits; the normal signup flow in the console
creates the same relationship.

## Test

```bash
curl -X POST "$ROOST_CONSOLE_URL/api/auth/validate" \
  -H "X-Service-Token: $INTERNAL_SERVICE_TOKEN" \
  -H "X-User-Id: $SUPABASE_USER_ID" \
  -H "Content-Type: application/json" \
  -d '{"check_quota":"chat"}'
```
