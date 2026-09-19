# Factor Board (因子看板)

The Factor Board has two surfaces, and the order matters:

- **因子库 (library)** — the factors the desk keeps. A factor is a row with an
  economic hypothesis, a lifecycle status, and the metrics of its last
  professional evaluation. This is the durable half.
- **因子检测 (detection)** — the one-click experiment: paste a script, get a
  verdict. Process-local, expendable, and where a new factor usually starts.

The library exists because a verdict with nowhere to live is not an asset. Before
it, a factor that scored well could not be compared with another, promoted, or
re-checked a month later — every look started from scratch.

## The library

`POST/GET /api/v1/factors/library` (see `src/server/app/factors.py`,
`src/server/services/factor_library.py`, `src/server/database/factor_library.py`).

| Endpoint | What it does |
|---|---|
| `GET /library` | This user's factors, filtered by status/source/text, plus the counts the filter chips show |
| `POST /library` | Save (upsert by name). **`hypothesis` is required** — an unexplained factor is data mining and the API refuses it |
| `GET /library/{id}` | One factor in full: hypothesis, code, formulation, raw metrics |
| `POST /library/{id}/evaluate` | Start a professional evaluation; 202, then poll the row |
| `POST /library/{id}/status` | `candidate` / `promoted` / `rejected` |
| `DELETE /library/{id}` | Remove a factor |

**Evaluation runs through `factor_evaluate`**, the miner tool added for this
purpose: it takes factor code and returns the alphalens-shaped tearsheet (quantile
returns, long-short spread, IC mean/IR/decay, turnover) plus a strict monotonicity
verdict per holding period, the IC half-life, and the IC t-statistic. Two panels:

| `dataset` | Panel | Measured wall time |
|---|---|---|
| `debug` (default) | the small static set (100 symbols) | ~36s |
| `full` | the windowed production panel (`window_days`, default 250) | ~65s on 5060 symbols |

**An edited factor loses its metrics.** `code_hash` (md5 of the code) is stored
next to the code, and a re-save whose hash differs drops `metrics`, clears
`last_evaluated_at` and demotes the factor to `candidate`. Those metrics describe
code that no longer exists; showing them next to the new code is how a stale
number gets read as a current one.

**Evaluation state lives in the row, not in a process.** `metrics.evaluation` is
written by whoever runs the job and read by whoever polls, so a reload, a second
device or another worker all see the same answer. A `running` row whose
`started_at` is older than the transport deadline (−60s of slack) is reported as
`lost` instead of spinning forever — a worker that died mid-evaluation is
actionable information.

### Why the library is LangAlpha's, not a live read of athena's

`docs` elsewhere described athena's own `factor_library` (Go/Postgres,
`get_factor_library` over MCP) as the source of truth. It is not used directly,
for three measured reasons:

1. **There is nothing in it.** The local table had 0 rows and the engine was not
   running, so a board that read it would render an empty page and could not be
   verified at all.
2. **LangAlpha cannot reach it in production.** The deployed backend talks to MCP
   through the hub (`/hub/mcp/alpha`); athena runs on a different host, so a live
   read would need athena registered as a hub upstream (infrastructure, not code).
3. **The sync problem only exists if athena is the only writer.** Making the
   library LangAlpha's turns athena into one *source* among the four the pipeline
   already names (user / agent / SOTA / athena), ingested through the same save
   path — `source` is a column on the row for exactly that. A live read would
   instead need a cache, a reconciliation rule and a failure mode for every page
   load.

If athena's library later holds factors worth showing, the ingest path is an
import that calls the same service, not a second read path.

## What one click runs

`POST /api/v1/factors/detections` starts a run and returns its id immediately.
The run then advances through stages, which the page polls:

| Stage | Tool | What it answers | Typical wall time |
|---|---|---|---|
| 契约检查 | `factor_execute` (debug panel) | Does the script satisfy the `result.h5` contract? | 6–50s |
| 近 20 日 IC | `factor_recent_ic` | Does the factor still predict over the trailing month? | ~280s |
| 近 60 日 IC | `factor_recent_ic` | The same over a quarter | ~280s |
| 样本外检验 | `factor_oos_check` | Mining window vs pure out-of-sample, plus relative decay | ~15s (or fails fast) |

Submit-and-poll is not a design preference: the IC probes are synchronous tools
that scan the full panel for minutes, so no HTTP request could carry the answer.
Progress is published stage by stage precisely so that a four-to-ten-minute wait
is legible.

The two IC probes run **sequentially on purpose.** The miner serves synchronous
tools from a two-worker pool, and firing both windows at once would occupy the
whole pool for the length of a detection — starving every other caller, including
the agent's own mining runs. Sequential costs wall-clock time; concurrent costs
the service.

## The verdict

`src/server/services/factor_detection.py` turns the findings into one headline:

- The contract check gates everything. A failed contract short-circuits to
  **未通过契约检查** — an IC measured over output that violates the panel shape is
  not evidence about the factor, and reporting the number would invite misreading
  it as merit.
- Otherwise the verdict is driven by the **largest-magnitude** IC across the
  probed windows, with `|IC| ≥ 0.05` strong and `≥ 0.02` usable.
- The out-of-sample stage is **advisory**: it refines the verdict and never gates
  it, so an OOS failure leaves the IC verdict standing.

## Configuration

The board talks to the **factor-miner-mcp gateway** — the service that answers
`POST /mcp` (JSON-RPC) and `GET /jobs/<id>`. That is a specific service, not "any
factor server": Athena's domain MCP (`~/project/athena`, port **51053**) exposes
the same tool *names* but no `/mcp` POST, so pointing the board at it fails at the
first call. Two gateways qualify today: a self-hosted `factor-miner-mcp`
(container `mcp-factor-miner`, port **50053**) or the hub's aggregated `alpha`
group.

| Variable | Default | Meaning |
|---|---|---|
| `FACTOR_MINER_URL` | `http://$HOST_IP:50053` | The gateway's HTTP base. In Docker `HOST_IP` resolves to `host.docker.internal`, which is where a host-run gateway binds. |
| `FACTOR_MINER_LICENSE_KEY` | *(empty)* | Sent as `X-License-Key`. Required only when the gateway has its own license file configured. |
| `FACTOR_MINER_TOKEN` | *(empty)* | Sent as `Authorization: Bearer`. This is the hub path. |
| `FACTOR_MINER_TIMEOUT` | `1800` | Per-run ceiling in seconds, covering a queued job and the whole probe battery. |

To point a deployment at the aggregated hub group instead of a local miner:

```bash
FACTOR_MINER_URL=https://causal-memory.com/hub/mcp/alpha
FACTOR_MINER_TOKEN=mcphub_<key>
```

An empty `FACTOR_MINER_URL` disables the board without breaking anything else:
every endpoint answers `503` with the reason instead of a traceback.

## Known limits

1. **`factor_oos_check` currently fails on the gateway side.** The handler raises
   `ModuleNotFoundError: No module named 'jinja2'` inside the container, so the OOS
   stage reports a failure. The board degrades correctly (the stage is marked
   failed, the IC verdict still stands), but the comparison is unavailable until
   the image installs `jinja2`.
   Getting that sentence onto the screen took three attempts, because the gateway
   reports the crash as `worker exception` in **both** its error fields and the
   real cause exists only in the job's `traceback`. `_job_failure_reason`
   therefore reads the traceback's last line first — verified against the live
   payload, which now surfaces as `ModuleNotFoundError: No module named 'jinja2'`
   rather than as a generic wrapper.
2. **`factor_recent_ic` is synchronous and slow.** It cannot be queued, so a
   detection holds a request open for minutes. The read timeout in
   `services/factor_miner.py` is sized to the whole call for exactly this reason —
   a short read timeout is indistinguishable from a dead server while the miner is
   in fact working.
3. **The miner stalls its own polls under load.** Its HTTP server is threaded, yet
   a `/jobs/<id>` read still stalled past 30s while a full-panel probe was
   running, which turned a healthy detection into a failure. Polling therefore
   tolerates up to `MAX_CONSECUTIVE_POLL_ERRORS` transport errors before giving
   up, and only a 404 (job gone) or a terminal job state is taken as definitive.
   This is a mitigation, not a diagnosis — the miner side of that stall has not
   been traced.
4. **The contract check is the flakiest stage.** Its sandbox has a hard 120s
   ceiling and the same script was measured at 6s and at 49s, so a timeout says
   more about load than about the factor. A sandbox timeout is therefore retried
   once (`CONTRACT_ATTEMPTS`, 2 minutes of bounded cost) before the run is
   declared failed; a real contract failure is never retried, because asking
   again will not change the shape of the output.

Run state is **process-local and expires after an hour** (`RUN_TTL_SECONDS`). A
backend restart drops in-flight runs, so the page treats an unknown run id as
404-and-re-submit rather than as "still running". The server defaults to a single
worker (`--workers 1`), which is what makes this sufficient; a deployment started
with several workers would need shared storage or sticky routing, or a poll could
land on a process that has never heard of the run.

## Live check

`scripts/factor_board_live_check.py` exercises the real router against the real
miner (templates → submit → poll → verdict). It is not a unit test: it depends on
a running miner and its panel, so it is run deliberately:

```bash
FACTOR_MINER_LICENSE_KEY=<key> HOST_MODE=oss \
  uv run python scripts/factor_board_live_check.py
```

It exits non-zero if the run fails or never settles.
