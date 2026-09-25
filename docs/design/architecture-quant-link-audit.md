# 架构 / 链路 / 依赖 / 结果去向 审计

> 审计日期 2026-09-23，全部来自源码与容器实测。结论先行：
> ① **qlib 的真实作用域只有三处**，其中两处已被我们自己的代码包了一层 —— 唯一没抽象的是**读 recorder**（这正是指标不可归因的根源）；
> ② **回测结果目前没有任何 DB 持久化**，且产物 TTL **24 小时**后连指标一起消失（今天实测：`/opt/mcp-suite/backtests` 只剩 12K、0 个 run 目录）。

---

## 1. 链路全景（实测）

```
人（LangAlpha 看板）        agent（athena / WeChat / CI）        RD-Agent（研究侧）
        │                            │                                 │
        │ REST /api/v1/factors/*     │ MCP tools/call                  │ bridge/runner
        ▼                            ▼                                 ▼
   langalpha-backend ──────────► MCPHub(:3100) ──────────────► mcp-factor-miner(:50053)
   （双归属网络直连 miner）              │                          │ 18 tools，auth=X-License-Key
                                        │                          │ 异步 job 队列（per-license 单槽）
                                        │                          ▼
                                        │                 mcp-factor-executor(:50054，不发布)
                                        │                          │ RLIMIT_AS 7168MiB / mem 4600m / 1800s
                                        │                          ▼
                                        │                    qrun conf.yaml（qlib 0.9.7）
                                        │                          │
                                        │                    mlflow 3.16.1（文件后端 ./mlruns）
                                        ▼                          ▼
                                   结果回流：result.json（唯一持久化写点）
                                        │
                              ⚠️ TTL 24h 后删除 → 指标随之消失
```

**实测到的唯一持久化写点**（miner 侧全仓检索）：
```
factor_executor/server.py:293   (job_dir / "result.json").write_text(json.dumps(result))
factor_miner/factor_backtest.py:599  combined.to_hdf(work_dir / "combined_factors_df.h5")
factor_miner/factor_backtest.py:357  out_path.write_text(rendered)   # conf.yaml
```
除这些文件外，**没有任何 INSERT/写库代码**；`sqlite3/psycopg/sqlalchemy/asyncpg` 在 miner 侧仅出现在 `mcp_gateway.py`（配额/许可计数）与测试里。

**TTL 与现状**：
```
factor_worker.py:47   CLEANUP_TTL_SEC = int(os.environ.get("FACTOR_MINER_CLEANUP_TTL_SEC", 24*3600))
实测：/opt/mcp-suite/backtests → 12K、0 个 run 目录   ← 今天跑的那几次已被删干净
```

---

## 2. qlib 依赖地图（精确到行）

| 位置 | 依赖什么 | 是否惰性 | 说明 |
|---|---|---|---|
| `factor_miner/qlib_dump_bin.py:30` | `qlib.utils.code_to_fname / fname_to_code` | 有 `try/except ImportError` 兜底 | **数据格式层**：`.bin` 命名与写入约定。**我们已自研实现**（且兜底了无 qlib 环境）→ 格式层其实已自主 |
| `factor_miner/gen_data.py:25-28` | `qlib.init` + `from qlib.data import D` | 惰性（`# noqa: PLC0415`） | **数据导出**：`.bin` → `daily_pv.h5` 面板 |
| `factor_miner/update_data.py:541-544` | 经 `gen_data._init_qlib` | 惰性 | **日更**：抓数 → dump bin → 重建 h5 |
| `factor_miner/factor_backtest.py:418-431` | `qlib.init` + `from qlib.workflow import R` | 惰性 | **⚠️ 读 recorder**：`R.list_experiments()` / `get_recorder()` 取 metrics |
| `factor_worker.py`（18 处提及） | 主要是把 qrun 交给执行器 / conf 渲染 | — | 逻辑层 |
| `mcp-factor-executor` 容器 | `qrun` + `qlib 0.9.7` + `mlflow 3.16.1` | — | **回测执行**：真正跑引擎的地方 |

**不依赖 qlib 的部分**（实测 0 提及）：`factor_eval.py`（因子评估 battery）、`analytics.py`（tearsheet/组合/regime/changepoint/vol）、`model_trainer.py`（ML 训练/预测）、`sandbox.py`（因子代码执行）。

### 结论：qlib 出现在三个真实位置，前两个已被包住

1. **数据格式（`.bin`/dump）** → 已有自研 `qlib_dump_bin.py` + 兜底 → **可视为自有格式层**（锁死风险低）；
2. **回测执行（qrun + conf + mlflow）** → 已有自研 conf 模板 + 执行器隔离 + 结果解析 → **引擎被包在容器里**（可替换性中等：换引擎要重写 `read_exp_res` 与 conf）；
3. **读 recorder（`factor_backtest.py:418-431`）** → **没有任何抽象**，且是 `R.list_experiments()` **"取最新 recorder"** 的写法 →
   **这就是 SigAna 三个指标逐位相同、而 ann/MDD 每次不同的直接机制原因**：
   指标不是按 "本次 run" 绑定取回的，而是"从共享 mlflow 里挑最新"。
   → **归因能力缺失**：跑完连"这行 metrics 出自哪个 run"都无法回答。

**隔离建议（不急着换引擎，先把契约与归因做对）**：
- run ledger 里记录 `engine=qlib@0.9.7` + `mlruns_run_id`，**指标一律按 run_id 显式取回**（不用 "最新 recorder"）；
- 把"引擎后端"作为适配器（`engine: qlib`），conf 模板与结果解析都挂在适配器下 —— 将来换引擎只换适配器；
- 数据格式继续用自己的 dump（已自主），**不要让 .bin 成为换引擎的障碍**。

---

## 3. 结果去向：现状 vs 应有

| 产物 | 现在在哪 | 活多久 | 谁能查 | 应有位置 |
|---|---|---|---|---|
| 回测 metrics（IC/年化/回撤…） | 调用方返回值 + `job_dir/result.json` | **24h** | 只有当时那次调用 | **DB：run ledger（metrics JSON）** |
| 净值曲线 / 成交明细 | `result.json`（内嵌） | 24h | 同上 | DB（曲线可落 JSONB/列存）+ 对象存储 |
| conf.yaml / combined_factors.h5 | job 目录 | 24h | 没人 | 保留为"可复现证据"，ledger 里存路径+hash |
| mlruns（qlib 自己的 run） | 执行器内 job 目录 | 24h | 没人 | 保留（ledger 存 mlruns_run_id） |
| exec_cache（因子值缓存） | 文件 LRU | LRU 淘汰 | 内部 | 保持文件（缓存不该进 DB） |
| 因子资产（人保存的） | `LangAlpha.factor_library`（metrics JSONB） | 永久 | 看板 | ✅ 已对；但**只在人 save 时才有**，与"回测 run"是两件事 |
| 挖矿 run（athena 侧） | `athena.db.mining_runs/mining_events` | 表在 | **0 行** | schema 已就绪但大脑未启用 |

**最严重的后果**（用今天的实测说）：**上周跑的因子 IC 是多少、用什么成本模型、哪份数据版本 —— 现在一条都答不出来**，因为 24h 前就被删了。
LangAlpha 的 `factor_library` 只覆盖"被人保存下来的因子资产"，覆盖不到"跑了但没保存"的绝大多数 run。

---

## 4. 落库设计（建议）—— ✅ 已实现（P0）

**接口**：`run_get(run_id)` / `run_list(limit, tool, status, tenant)`（run_id 就是重任务提交时返回的 `job_id`，不再有第二套编号）。

**实现位置**：
- `factor_miner/run_ledger.py`（新）—— SQLite，库文件 `/app/usage/quant_runs.db` →
  宿主 `/opt/mcp-suite/usage/factor-miner/quant_runs.db`（**在挂载盘上，不参与 backtests 的 TTL 清理**）
- 写入点：`mcp_gateway.py::_worker` 作业终态落定处（**best-effort，台账失败绝不影响作业终态**）
- 归因字段来源：`factor_worker._run_backtest` 随结果返回 `data_version / engine / code_hashes / spec / artifacts_dir`

```sql
CREATE TABLE quant_runs (
  run_id, tool, tenant, status, ok,
  engine,          -- qlib（版本由执行器镜像固定）
  spec,            -- profile / windows / factor 名单
  data_version,    -- 面板 sha256（已有 data_version()）
  code_hashes,     -- 因子名 → cache_key(code, version)
  mlruns_run_id,   -- 待补：执行器尚未回传
  artifacts_dir, metrics, net_curve, elapsed_sec,
  error_code, error_msg, created_at, finished_at
);
```

**实测验证（2026-09-25）**：
```
提交 baseline 回测 → job_id ad3505b18f2d → done @60s
run_get(ad3505b18f2d) →
  metrics      = {IC: 1.55e-17, RankIC: NaN, ICIR: 0.22337, ann: -0.3118, MDD: -0.0742}
  data_version = sha256:9e54bbe8e072d01759eefd059affac5e3
  spec         = {profile: smoke, baseline: true, windows: {}, sota: [], new_factors: []}
  artifacts_dir= /work/backtests/bc6bb975b67649f68229947682b1e59c
★ 决定性演示：删掉该产物目录后，run_get 仍返回完整 metrics —— 这正是"结果没存 DB"被补上的证据
```

**两个实现细节（都踩过）**：
1. `RankIC` 在 smoke 档常是 `NaN`，`json.dumps` 会写裸 `NaN`（**非法 JSON**）→ LangAlpha 是 TS/JS，
   `JSON.parse` 直接抛。已在**写入与读取两侧**都做 `_sanitize`（NaN/Inf → null），含修复前的历史脏行。
2. 台账放在 `/app/usage/`（挂载盘）而不是 `/work/`（backtests 卷）——**放在 /work 会被自己的 TTL 清掉**。

### 仍待补（下一步）

- `mlruns_run_id`：执行器尚未回传 qrun 的 mlflow run id；补上后 `run_get` 就能**按 run 显式取指标**，
  彻底替掉 `read_exp_res` 里"取最新 recorder"的写法（也才能最终查清 SigAna 三指标重复之谜）。
- **产物保留期**：ledger 保住了指标，但要复现/排查仍需 mlruns 等大文件；建议大文件 TTL 提到 30/90 天，
  并在 ledger 记 `artifacts_deleted_at`。

---

## 5. 一页结论

| 问题 | 结论 |
|---|---|
| 底层是否被 qlib 锁死？ | **部分**：数据格式已自主（自研 dump + 兜底）；引擎（qrun/conf/mlflow）被容器包住；**唯一裸奔的是"读 recorder"**，且正是指标不可归因的根源 |
| 结果存 DB 了吗？ | **完全没有**。唯一写点是 `result.json` 文件，**TTL 24h**；今天实测 backtests 只剩 12K、0 个 run |
| 最该先补什么？ | ① **run ledger 落 DB**（含 data_version/seed/mlruns_run_id）；② **指标按 run_id 显式取回**（不用"最新 recorder"）；③ TTL 只管中间产物，别删指标 |
| 与被 qlib 绑定的风险比 | 数据格式 < 引擎 < **归因**（归因是纯自研就能解决的，且收益最大） |
