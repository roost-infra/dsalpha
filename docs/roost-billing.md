# Roost Billing (dsalpha)

dsalpha can use the Roost Console as its quota service instead of the legacy
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

## Sandbox usage

A closed `computer_runs` row is reported to Roost once, by
`services/sandbox_billing.py` on a loop started with the server. The console
resolves the Supabase user to an organization and debits that wallet in the
same transaction as the detail row:

```text
POST /internal/v1/orgs/resolve-user    {"user_id": "<supabase user id>"}
POST /internal/v1/usage/sandbox        {org_id,user_id,product:"dsalpha",...}
```

The price is Daytona's list rate, marked up 1.3× and converted at
`USD_TO_CREDITS_RATE`:

| Resource | Daytona rate | Included |
|---|---|---|
| CPU | `$0.0504` / vCPU-hour | — |
| Memory | `$0.0162` / GiB-hour | — |
| Disk | `$0.000108` / GiB-hour | first 5 GiB |

```text
hours        = billable_seconds / 3600
cpu_credits  = cpu_cores * hours * 0.0504 * 720 * 1.3
mem_credits  = memory_gb * hours * 0.0162 * 720 * 1.3
disk_credits = max(disk_gb - 5, 0) * hours * 0.000108 * 720 * 1.3
total        = ceil(cpu + mem + disk), at least 1 when anything was used
```

The billing columns on `computer_runs` (migration 118) record the settlement:
`billing_reported_at`, `billing_credits`, and the last `billing_error`. A 402
insufficient-credits answer, a 401/403/404 configuration or account answer,
429, a 5xx, or a network failure leaves the run queued and is retried on the
next cycle. A malformed report the console will always refuse is settled with
its error so it leaves the queue.

```bash
SANDBOX_BILLING_INTERVAL_SECONDS=300   # reporter cycle
SANDBOX_MARKUP_BPS=13000               # 1.3×, in basis points
DAYTONA_CPU_USD_PER_HOUR=0.0504
DAYTONA_MEMORY_USD_PER_GIB_HOUR=0.0162
DAYTONA_DISK_USD_PER_GIB_HOUR=0.000108
DAYTONA_DISK_FREE_GIB=5
```

Known limits, deliberately not papered over:

- **Running interval only.** A stopped Daytona sandbox keeps its disk, but
  `computer_runs` has no disk-only or paused interval, so that storage is not
  billed yet. A pause is billed as the interval before it and the interval
  after it resumes, not as the pause.
- **No historical backfill.** Only runs closed after migration 118 shipped are
  in the reporter's queue.
- **One reporter per cycle.** A Postgres session advisory lock admits one
  worker; a duplicate report that slips through is a 200 replay under the same
  idempotency key (`dsalpha:computer_run:<run_id>`), so it is not a second
  charge.
- **Console scope.** The `dsalpha` service secret must allow both routes above.
  The console currently allows `/internal/v1/usage/sandbox` for `dsalpha` but
  not `/internal/v1/orgs/resolve-user`; until that is added, reports stay
  queued with a 401/403 in `billing_error` rather than being lost.

## Account mapping

The compatibility lease routes create a personal org on first use when the
user has none. `resolve-user` is read-only and answers 404 until that
relationship exists, so a user who has never hit a billed path has no org to
report sandbox usage against. The reporter treats that as retryable: the run
is billed once the relationship appears.

## Test

```bash
curl -X POST "$ROOST_CONSOLE_URL/api/auth/validate" \
  -H "X-Service-Token: $INTERNAL_SERVICE_TOKEN" \
  -H "X-User-Id: $SUPABASE_USER_ID" \
  -H "Content-Type: application/json" \
  -d '{"check_quota":"chat"}'
```
