# 量化能力层（MCP 封装层）设计

> 目标一句话：**把「回测/因子/组合」这层能力封装成 agent 直接可用的类型化契约，让 agent 不必写回测引擎代码，人也不必操作 GUI。**
>
> 本文的缺口清单全部来自**实测踩坑**（2026-09 这一轮集成），不是设想；每条都标了证据。

---

## 0. 定位：我们卖的是"那一层"

三种形态对比，说明为什么封装层的价值在"中间":

| 形态 | 谁写引擎代码 | 谁操作 | 代表 |
|---|---|---|---|
| 传统量化系统 | 平台作者（闭源） | **人点 GUI** | 看海 KHQuant（PyQt5，MiniQMT） |
| "AI 量化"（裸用 LLM） | **agent 自己写回测引擎** | agent | 让模型从零实现回测循环/撮合/绩效 |
| **我们** | **平台作者（已封装）** | **agent 调用** | MCP 工具：`factor_backtest` / `factor_evaluate` / `factor_oos_check` … |

→ 我们的护城河不是"又一个引擎"，而是 **把引擎、数据、沙箱、资源护栏、可复现性都封装成契约**，
让 agent 只表达**意图**（跑什么因子、什么universe、什么成本、什么窗口），不表达**实现**。

---

## 1. 现状盘点（已有，实测）

**18 个工具**，分四类：
- 执行/回测：`factor_execute`、`factor_backtest`、`factor_oos_check`、`factor_daily_compute`
- 评估：`factor_evaluate`、`factor_recent_ic`、`factor_tearsheet`
- ML：`ml_train_rolling`、`ml_predict`、`ml_metrics`
- 分析/数据：`portfolio_optimize`、`regime_detect`、`change_point`、`vol_forecast`、`compute_factors`、`predict`、`update_data`、`job_status`

**支撑设施（比工具本身更值钱）**：
- `mcp-factor-executor` 独立容器：cgroup `mem_limit 4600m` + `RLIMIT_AS 7168MiB` + `timeout 1800s`（qrun 峰值实测 3.58GB）
- 异步 job 队列（per-license 单槽）+ 磁盘 TTL 清理
- 沙箱：AST 白名单 + rlimit + 120s（LLM 代码不触网、不带凭证）
- 鉴权 `X-License-Key` + MCPHub（10 server）+ `quota-platform`
- 数据：qlib `.bin` 846MB（6152 标的）+ 面板 h5 405MB + `data_version`（sha256 面板版本）

---

## 2. 缺口清单（都是实测踩出来的）

| # | 缺口 | 实测证据 | 对 agent 的后果 |
|---|---|---|---|
| **G1** | **回测参数无法表达**：只有 `profile: full\|smoke` 两个字符串，universe/窗口/成本/策略参数全烘焙在模板里 | 想看 30 票/2019 只能选 `smoke`；`open_cost 0.0005 / close_cost 0.0015 / topk 50 / n_drop 5` 都是 conf 里写死的 | agent 没法问"csi500 + 10bp 成本 + topk 30 + 训练窗口 2010-2016"——**只能改代码或加 profile**，这正是"要 agent 写引擎"的根源 |
| **G2** | **上游隐式契约会漏到调用方**：我不止一次撞到"某一层要求精确 key/名字" | `feedback` 层硬编码 3 个 metric key；metrics Series 必须 name=`"0"`；`job_status` 成功终态是 `done` 不是 `ok` | agent 必须猜隐式约定；错一次就是一个看不懂的 `KeyError` |
| **G3** | **可复现性无保障**：随机性 + 无 seed + 无输入 manifest | 同一因子 smoke 多次跑：ann/MDD 每次不同（-0.263/-0.289/-0.258）；更甚者 SigAna 三个指标**逐位相同**（疑 `read_exp_res` 取到共享 mlflow 的同一 recorder） | 结果不可复现 → 无法做准入决策，也无法追责 |
| **G4** | **失败不可诊断**：错误是自然语言字符串 | `"factor_backtest worker exception"`、`"new factor 'ma_5' failed"`、`"你已有一个重任务在执行/排队中"`；`traceback` 另一个字段 | agent 无法据此决定"重试/换参数/放弃"，只能瞎试 |
| **G5** | **job 只有 status，没有控制与列表** | 只有 `job_status`；单槽被卡住的 handler 占死后必须重启容器才恢复 | 并发即互相拒绝；卡死无解；agent 无法取消或看队列 |
| **G6** | **没有 run 台账/产物取回**：跑完只回 `metrics/net_curve/trades`，run 与输入的对应关系不持久 | 产物散在 `/work/backtests/<hash>/`，靠 TTL 清理；没有 `run_id` 概念 | 事后无法回答"这个指标是哪次跑的、什么参数、什么数据版本" |
| **G7** | **数据能力薄**：只有 `update_data`（且实测 4 次 3600s 超时）+ 无状态查询 | 东财 502 / mootdx bestip / 覆盖率 155-5204；面板版本只在 exec 日志里 | agent 不知道数据是否新鲜/覆盖够不够，回测会**静默用旧数据** |
| **G8** | **许可/配额是横切关注点但工具不自知** | `-32001 invalid or missing license key`；`-32029 busy`；配额在独立服务 | agent 无法预判"我还能跑几次/多贵" |
| **G9** | **只给机器看的输出** | tearsheet 是 JSON；人要看图得进 LangAlpha 看板 | 迭代效率低（人要介入看结果） |

---

## 3. 设计：三层封装 + 四条横切

```
┌─ L3 工作流能力（一次调用 = 一个专业动作）───────────────────────────┐
│  walk_forward / oos_admission / sweep / portfolio_backtest /       │
│  factor_mine(可选，接 RD-Agent 桥) / report                        │
├─ L2 原子能力（可组合，agent 编排）─────────────────────────────────┤
│  backtest（类型化 BacktestSpec）· evaluate · tearsheet ·            │
│  ml_train/predict · portfolio_optimize · regime/changepoint/vol    │
├─ L1 数据与运行（agent 不该自己管）─────────────────────────────────┤
│  data_status · data_refresh · run_get · run_list · job_* · cache   │
└────────────────────────────────────────────────────────────────────┘
横切：① 契约与版本 ② 可复现(run ledger + seed) ③ 错误码与预算 ④ 双出口(MCP + CLI/报告)
```

### 3.1 核心改造：`profile` 字符串 → **类型化 `BacktestSpec`**（治 G1）

```jsonc
// tools/call factor_backtest  (v2)
{
  "factors":  [{"name": "mom_5d", "code": "…"}],        // 新因子（代码，不是表达式）
  "sota":     [{"name": "alpha158", "code": "…"}],      // 可选，基线对比
  "universe": {"kind": "index", "name": "csi500"}       // 或 {"kind":"list","symbols":[…]}
              | {"kind": "preset", "name": "smoke"}     // 兼容旧 profile
  ,
  "window":   {"train": ["2010-01-01","2016-12-31"],
               "valid": ["2017-01-01","2017-12-31"],
               "test":  ["2018-01-01",null]},
  "cost":     {"open_bp": 5, "close_bp": 15, "min_cost": 5},   // 显式成本模型（不再写死）
  "strategy": {"class": "TopkDropout", "topk": 30, "n_drop": 5},
  "model":    {"class": "LGBModel", "num_leaves": 210, "num_threads": 20},
  "seed":     42,                                       // 治 G3（含 n_drop 随机）
  "baseline": false,                                    // 纯 Alpha20 基线（已有）
  "report":   {"format": "none|json|html"}              // 治 G9
}
```
**兼容**：`profile` 保留为 `universe`+`window` 的语法糖（老调用与 RD-Agent 桥不受影响）。
**实现要点**：conf 模板已用 Jinja 预渲染（`_render_conf` / `_render_windows_conf`）→ 变成"渲染 `BacktestSpec`"即可，不需要新引擎。这是**小改动、大收益**。

### 3.2 可复现：**Run Ledger**（治 G3/G6）

每次重任务落一行（表或 JSONL 落盘 + 可查）：
```
run_id · tool · license/tenant · 输入摘要(因子 code_hash, spec, 数据版本 sha256) ·
seed · 开始/结束 · 状态 · metrics · 产物路径(conf/qlib_res.csv/ret.pkl/mlruns) · 成本
```
并新增 `run_get(run_id)` / `run_list(limit, tool, status)`。
**顺带解决 SigAna 疑点**：`run_get` 回传的 metrics 必须与 `mlruns/<exp>/<run>/metrics` 逐项一致，
一致性由 `run_id → mlruns 路径` 的显式绑定保证（现在是"读最新 recorder"，天然不可追）。

### 3.3 错误码化（治 G4）

统一 envelope：
```json
{"ok": false,
 "error": {"code": "FACTOR_CODE_FAILED|DEDUP_DROPPED|DATA_STALE|BUSY|QUOTA|BAD_SPEC|ENGINE_MEMORY",
           "message": "…", "hint": "可行动的下一步", "retryable": true,
           "details": {"factor": "ma_5", "stderr_tail": "…"}}}
```
现有语义映射：`FactorEmptyError`→`DEDUP_DROPPED`（可重试换方向）、`MemoryError`→`ENGINE_MEMORY`（降 profile/窗口）、
`-32029`→`BUSY`（`retryable:true` + `retry_after`）、`-32001`→`AUTH`。
**让 agent 能自己决定重试/换参/放弃**，这是"封装好"的核心标志。

### 3.4 数据即服务（治 G7）

- `data_status()` → `{panel_version, last_trading_day, coverage_ratio, instruments, stale_days, qlib_version}`
- `data_refresh(scope, force)` → 把现有 `update_data` 拆成"可观测的作业"（阶段进度 + 失败阶段），
  并修掉现在的 4 连超时（东财 502/mootdx bestip/覆盖率校验已有代码，缺的是**分段上报 + 部分成功语义**）
- 回测前置校验：`data_status` 不满足 → `DATA_STALE` 直接拒（**禁止静默用旧数据**）

### 3.5 并发与配额（治 G5/G8）

- 由"per-license 单槽 + 阻塞拒绝"升级为**小队列 + 公平调度**：`queue_depth`、`eta_sec`、`job_cancel`、`job_list`
- **看门狗**：`MCP_JOB_TIMEOUT_*` 触发后强制回收 handler 占位（现在必须重启容器）
- `budget()` → 剩余配额/预估成本（CPU 秒、内存峰值、token），让 agent 先问再跑

### 3.6 能力自描述（治 G2/G8）

`capabilities()` 返回：工具清单 + 参数 schema + **一份"怎么用"的协议说明**（哪些是隐式契约，例如
"metrics 必须含 IC/…/max_drawdown 三键"、"baseline 与因子轮必须同 profile 才可比"）。
让隐式契约**显式化**，而不是靠 agent 读源码或撞墙。

### 3.7 双出口（治 G9）

同一套能力两个门面：
- **MCP**：给 agent（本文主体）
- **CLI + 报告**：给人/CI。`factor_backtest` 已有 argparse `main()`，
  补 `--report html`（用 `net_curve` + `trades` + metrics 渲染）→ "一条命令出报告"，
  直接补上我们在对比看海时承认的短板（**人看的报告 + 低门槛**）。

---

## 4. 分阶段落地

| 阶段 | 内容 | 治哪几个缺口 | 量 | 状态 |
|---|---|---|---|---|
| **P0** | **Run Ledger 落库 + `run_get`/`run_list`**（含 data_version/code_hashes/spec/artifacts_dir） | **G3、G6** | 1 天 | ✅ **已完成并实测**（`factor_miner/run_ledger.py` + 网关挂钩 + 两个工具；删产物后台账仍可查） |
| **P0** | `BacktestSpec`（universe/window/cost/strategy/model/seed）+ `profile` 兼容层 | G1、G3(半) | 1 天 | ⏳ |
| **P0** | 错误码 envelope + `capabilities()` | G4、G2 | 0.5 天 | ⏳ |
| **P1** | `mlruns_run_id` 回传（按 run 显式取指标，替掉"取最新 recorder"）+ 产物保留期 | G3、G6 | 0.5 天 | ⏳ |
| **P1** | `data_status()` + 回测前置拒旧数据 + `update_data` 分段上报 | G7 | 0.5 天 | ⏳ |
| **P2** | 小队列 + `job_cancel`/`job_list` + 看门狗（回收卡死槽位） | G5 | 1 天 | ⏳ |
| **P2** | `budget()` + 配额联动；`report: html`（CLI 门面） | G8、G9 | 1 天 | ⏳ |
| **P3** | 工作流工具：`walk_forward`、`oos_admission`、`sweep` | 组合能力 | 2-3 天 | ⏳ |

**验收（可执行的）**：
1. 同一个 `BacktestSpec` + `seed` 跑两次 → `metrics` 逐位一致（现在不一致 → 直接证伪/证实 G3）；
2. `data_status` 面板过期时，回测返回 `DATA_STALE` 而不是给结果；
3. 故意传坏 spec → 返回 `BAD_SPEC` + `hint`，且 agent 仅凭 envelope 就能自愈；
4. `run_get(run_id).metrics` 与 `mlruns/<exp>/<run>/metrics` 逐项一致（销掉 SigAna 疑点）；
5. 卡死的重任务被看门狗回收，无需重启容器（现在必挂）。

---

## 5. 一句话

看海把量化**关进 GUI**，裸 LLM 方案让 **agent 自己写引擎**；我们把**引擎/数据/沙箱/护栏封装成类型化契约**，
agent 只说意图、不说实现 —— 那就必须把 §2 那 9 个缺口补上，而不是再加第 19 个工具。
