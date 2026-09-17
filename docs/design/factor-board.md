# Factor Board (因子看板)

The Factor Board is the read surface for the factor mining pipeline. Mining
already produces candidates — `factor-miner-mcp` owns the A-share panel, the
sandbox and the evaluator — but a candidate that has never been *looked at* is not
a decision. This page is the one-click path from a factor script to a verdict.

Route: `/factors` (sidebar → 因子看板 / Factor Board).

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

### Reachability is not enough: the credential is a separate deployment step

A self-hosted gateway with a license file configured answers `{"auth": true}` from
`/health` and rejects every `tools/call` without an `X-License-Key`, so a
deployment that sets `FACTOR_MINER_URL` and stops there has a board that *looks*
configured — the health banner reads reachable — and 401s on every detection.
Both variables are required in that case, and they come from different places:

```bash
# From the gateway's own license file: {"keys": {"ak_...": {...}}}
FACTOR_MINER_URL=http://<gateway-host>:50053
FACTOR_MINER_LICENSE_KEY=ak_<...>
```

In Docker Compose that means the key belongs in the backend service's `env_file`
(`.env`), not only in the environment block. This was observed live: a production
deployment had `FACTOR_MINER_URL` set and the key unset.

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
