# Roost Billing (dsalpha)

dsalpha can use the Roost Console as its quota service instead of the legacy
`quota-service`. No product-side lease code changes beyond configuration:
the existing `PlatformCreditGatePort` talks to the compatibility routes.

## Environment

```bash
AUTH_SERVICE_URL=https://www.roostbots.com/console-api
INTERNAL_SERVICE_TOKEN=<Roost API SERVICE_SECRET>
HOST_MODE=platform
```

The USD→credit rate and the sandbox markup are **console settings**, not local
configuration: the server reads `fx.usd_to_credits` and `sandbox.markup_bps`
from Roost Console at startup (`services/billing_rates.py`) and refreshes them
every `BILLING_RATES_INTERVAL_SECONDS` (default 300). A changed setting reaches
a running deployment without a deploy.

`USD_TO_CREDITS_RATE` / `SANDBOX_MARKUP_BPS` are only the fallback for an OSS
or console-less deployment, or one whose console has never answered. The old
`USD_TO_CREDITS_RATE=720` line is no longer required; setting it explicitly is
warned about at boot when it disagrees with the console, because the console
value is the one used. The code default is 720 (was 1000, a third undocumented
rate); the hard-coded "canonical credit unit" check is gone.

## Compatibility surface

Roost exposes the same paths the legacy quota service used:

```text
POST /api/auth/validate
POST /api/auth/billing/leases/acquire
POST /api/auth/billing/leases/release
GET  /api/auth/billing/leases/capability
```

The release settles the turn against the organization wallet exactly once. Its
payload is the console contract's:

```json
{
  "user_id": "…", "run_ref": "…", "generation": 3, "byok": false,
  "model_usage": [{ "model": "claude-sonnet-5.5", "input": 150000,
                    "output": 2000, "cache_read": 0, "cache_write": 0,
                    "calls": 3 }],
  "spent_usd": 0.0123
}
```

`model_usage` is aggregated from the turn's own per-call records, platform
calls only (BYOK calls are the user's own spend and would be charged twice);
cache tokens are split out of LangChain's inclusive `input_tokens` into their
own components. Model names are respelled to the public price book's spelling
(`claude-sonnet-5-5` → `claude-sonnet-5.5`) so the console can price them
instead of answering `unknown_model`.

`spent_usd` is the transitional scalar fallback, compared against the console's
`charged_credits` on every release; a model more than 5% off the book is logged
and is what retires the fallback. `spent_credits` is still sent for a legacy
quota service and ignored by the console. `byok=true` records the usage without
debit.

A release with no spend figure at all is **not** sent: releasing it would
retire the whole reserved ceiling and give the turn away. The run is marked
`billing_settle_pending` (migration 127) and the settlement worker
(`services/billing_settlement.py`) later reads its `conversation_usages` row —
the durable record finalize writes just after teardown — and settles with the
same `model_usage` / `spent_usd` payload. Retryable failures (402, 401/403/404,
429/5xx, network) leave it queued; an answer nothing can change (400/409/422)
settles it with the reason so the queue drains. A failed inline release queues
the run the same way instead of letting the lease expire unbilled.

## Sandbox usage

A closed `computer_runs` row is reported to Roost once, by
`services/sandbox_billing.py` on a loop started with the server. The console
resolves the Supabase user to an organization and debits that wallet in the
same transaction as the detail row:

```text
POST /internal/v1/orgs/resolve-user    {"user_id": "<supabase user id>"}
POST /internal/v1/usage/sandbox        {org_id,user_id,product:"dsalpha",...}
```

The report is usage-only for pricing purposes: the console prices the interval
from its own `sandbox.markup_bps` and `fx.usd_to_credits` settings. The legacy
`*_credits`, `total_credits` and `unit_prices` fields are still sent during the
transition, and the console's `charged_credits` is compared with the local
estimate — a difference is logged and the console's figure is what the run
records. The local estimate uses Daytona's list rate, the console markup and
the console fx:

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
SANDBOX_MARKUP_BPS=13000               # fallback only; console settings win
BILLING_RATES_INTERVAL_SECONDS=300     # fx/markup refresh cycle
BILLING_SETTLEMENT_INTERVAL_SECONDS=120  # pending-settlement worker cycle
DAYTONA_CPU_USD_PER_HOUR=0.0504
DAYTONA_MEMORY_USD_PER_GIB_HOUR=0.0162
DAYTONA_DISK_USD_PER_GIB_HOUR=0.000108
DAYTONA_DISK_FREE_GIB=5
```

The body's usage quantities are `billable_seconds`, `cpu_cores`, `memory_gb`,
`disk_gb`, `gpu_seconds` plus the resource×time fields (`cpu_seconds`,
`memory_mib_seconds`, `disk_mib_seconds`).

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
