# RD-Agent 完整集成 Runbook

> 目标：把 RD-Agent 的「假设 → 写因子代码 → 回测 → 反馈进化」这条循环，**完整**接到我们已有的
> LangAlpha + factor-miner-mcp + 数据/执行层上。**不 fork RD-Agent 源码、不引入 Docker/conda、不复制 QuantMind 的 AGPL 代码。**
>
> 状态时间：2026-09-23。凡标注 ✅ 的都当场验证过（附命令与输出）。

---

## 0. 「完整」= 五层，逐层状态

| 层 | 要解决什么 | 做法 | 状态 |
|---|---|---|---|
| **L1 执行层** | 回测跑在哪 | `bridge/runner.py` 用 miner MCP 替代 `qrun`/Docker/conda | ✅ **已实现 + 自检通过** |
| **L2 数据层** | 因子代码读哪份数据 | 预置 `git_ignore_folder/factor_implementation_source_data{,_debug}/daily_pv.h5` | ✅ **已完成 + 验证不触发 Docker** |
| **L3 落库层** | 产出的因子落到哪 | LangAlpha `factor_library`（`source='rdagent'`）+ run 台账 | ⏳ 待做（半天） |
| **L4 触发层** | 谁来发起一轮挖掘 | 注册 `rdagent` MCP server 进 MCPHub | ⏳ 待做（1 天） |
| **L5 治理层** | 成本/质量/并发/安全 | 单槽位看门狗、token 记账、去重闸门、OOS 准入、受限解释器 | ⏳ 部分 |
| **L1+L2 端到端首跑** | 上面两层真的能跑循环 | `rdagent fin_factor` 带 `step_n=1` | ⏳ 待跑（需 ~20 分钟 + LLM token） |

---

## L1 执行层 ✅（已实现并验证）

### 接在哪、为什么

RD-Agent 的 `QlibFactorRunner.develop()` 才是「因子代码 → 合并 → 回测 → 指标」那一步
（`scenarios/qlib/developer/factor_runner.py:70`）；而 factor-miner 的
`factor_backtest(sota, new_factors, profile)` 做的**恰好是同一件事**——
其 `conf_combined_factors.yaml` 本来就是从 RD-Agent 的 `factor_template/` 移植的，
指标口径一致（统一 `with_cost`、`FactorEmptyError` 语义）。

所以接在 **runner**：连"在哪个解释器里跑因子代码"都不再需要（宿主机不需要 qlib / conda / Docker）。

### 产物契约（三处硬要求，缺一个就炸）

| 契约 | 出处 | 我们的做法 |
|---|---|---|
| `exp.result` 必须是含 `IMPORTANT_METRICS` 三个精确 key 的 Series | `developer/feedback.py:18-21`（`process_results` 里 `.loc[IMPORTANT_METRICS]`） | `metrics_to_series()` 显式映射；缺 key 时**提前抛**而不是等 KeyError |
| 工作区要有 `qlib_res.csv` | `experiment/workspace.py:52`（`pd.read_csv(index_col=0).iloc[:,0]`） | `_write_back()` 写 |
| 工作区要有 `ret.pkl` | `experiment/workspace.py:46`（缺它 `execute()` 直接 `return None` → 上层抛 `FactorEmptyError`） | 用 miner 的 `net_curve` 写 DataFrame |

映射表：
```
metrics["IC"]                        → "IC"
metrics["annualized_return_with_cost"] → "1day.excess_return_with_cost.annualized_return"
metrics["max_drawdown"]              → "1day.excess_return_with_cost.max_drawdown"
（另保留 RankIC / ICIR，feedback 只取上面三个，多的无害）
```

### 文件与启用

```
~/project/RD-Agent/bridge/
├── miner_client.py   MCP 客户端（走 :50053，不走未发布的执行器 :50054）
├── runner.py         FactorMinerRunner(QlibFactorRunner) —— 覆盖 develop()
├── selftest.py       不跑 LLM 的自检（真回测 + 产物契约）
└── __init__.py
```

```bash
export QLIB_FACTOR_RUNNER=bridge.runner.FactorMinerRunner   # 零 fork 注入
export FACTOR_MINER_MCP_URL=http://127.0.0.1:50053/mcp      # 跨机用 SSH 隧道
export MCP_LICENSE_KEY=<miner 的 license key>               # miner auth=on，必需
export FACTOR_MINER_PROFILE=smoke                           # 或 full
```

### 自检结果（实跑，45 秒）

```bash
MCP_LICENSE_KEY=... .venv/bin/python -u -m bridge.selftest
```
```
[0] 上游 IMPORTANT_METRICS = ['IC', '1day.excess_return_with_cost.annualized_return',
                              '1day.excess_return_with_cost.max_drawdown']
[1] collect_factors ok → ['bridge_probe_mom2']
[2] 向 miner 提交 factor_backtest(profile=smoke) …
    [miner 960d98238ee6] status=running elapsed=10s
    [miner 960d98238ee6] status=running elapsed=21s
    [miner 960d98238ee6] status=running elapsed=31s
    [miner 960d98238ee6] status=done    elapsed=42s
    ✓ ok，metrics={IC, RankIC, ICIR, annualized_return_with_cost, max_drawdown}
[3] metrics 映射 ok（feedback 层三个硬编码 key 齐了）
[4] 产物 ok → qlib_res.csv + ret.pkl 都写出来了
✅ 桥自检通过：RD-Agent 的因子代码已经能在生产 miner 上跑出指标，且满足上游产物契约。
```
> MD5/产物细节：`bridge_probe_mom2` 那个 42s 的 smoke 回测走的是**真实** miner → 真实执行器容器 → 真实 `qrun`。

### 三个已经踩过的坑

1. **job 的 `status` 是 `queued/running/done/error`，没有 `ok`。**
   `mcp_gateway.py:367 JobQueue`：成功终态是 **`done`**；`ok` 只是 `mcp_tool_calls_total` 的计数标签。
   我第一版按 `{"ok","error"}` 判断 → **作业早就跑完了，轮询却永远不返回**（表现为"挂住"，两次都是这个原因）。
2. **`X-License-Key` 必需**：miner `auth=on`，缺头直接 `-32001 invalid or missing license key`（在 `initialize` 之后、`tools/call` 时才报）。
3. **重任务是 per-license-key 串行单槽**：同 key 已有 `queued/running` 的作业 → 后续提交抛
   `-32029 你已有一个重任务在执行/排队中`。**注意**：这不是"提交被丢弃"的可靠信号——
   实测中出现过拿不到 `job_id` 但作业其实已在跑的情况，所以调用方在 busy 时应当用
   `/metrics` 或作业台账核对，而不是假定没提交上。（此前我在另一份文档里把它写成"误报"，不准确，已修正。）

---

## L2 数据层 ✅（已完成并验证）

RD-Agent 有**两处**绕不开 Docker，只有都处理掉才算真免 Docker：

| # | 位置 | 行为 | 我们怎么绕 |
|---|---|---|---|
| 1 | `scenarios/qlib/experiment/utils.py:13 generate_data_folder_from_qlib()` | **无条件** `QTDockerEnv()` 生成数据目录 | 预置两个目录（`get_data_folder_intro` 只在**缺失时**才调它） |
| 2 | `components/coder/factor_coder/factor.py::FactorFBWorkspace.execute()` | 裸 `subprocess` 在宿主机跑 LLM 生成的因子代码 | 设 `FACTOR_COSTEER_PYTHON_BIN` 指向受限解释器（**安全红线**，见 L5） |

已落地（拷自生产面板，避免第二份数据导致日历漂移）：

```
git_ignore_folder/factor_implementation_source_data/daily_pv.h5         404M  （生产 daily_pv_all.h5）
git_ignore_folder/factor_implementation_source_data/README.md           717B  （schema 说明，LLM 会读）
git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5   1.3M  （生产 daily_pv_debug.h5）
git_ignore_folder/factor_implementation_source_data_debug/README.md     325B
```

验证（9 秒返回，**未触发 Docker 生成**）：
```bash
.venv/bin/python -c "from rdagent.scenarios.qlib.experiment.utils import get_data_folder_intro; print(len(get_data_folder_intro()))"
# → 792
```

---

## L1+L2 端到端首跑（✅ 已跑；循环走到 feedback，剩一个 baseline 缺口）

### 实跑记录（2026-09-23，本机 M2）

跑法（三个修复缺一不可）：
```bash
export STEP_SEMAPHORE=1 MODEL_CoSTEER_ENV_TYPE=conda
export QLIB_FACTOR_RUNNER=bridge.runner.FactorMinerRunner
export FACTOR_MINER_MCP_URL=http://127.0.0.1:50053/mcp   # 跨机走 SSH 隧道
export FACTOR_MINER_PROFILE=smoke
export FACTOR_COSTEER_PYTHON_BIN=/Users/hjx/project/RD-Agent/.venv/bin/python  # ★ 本机没有 `python`
export QLIB_FACTOR_EVOLVING_N=1
.venv/bin/rdagent fin_factor --loop-n 1      # 注意是 loop-n（step-n 只是单步）
```

**到达的步骤**：`direct_exp_gen → coding → running → feedback → record`，
其中 `running` 步骤**真的走了我们的桥**：

```
[miner 32ec2d7c3525] status=running elapsed=…263s
[miner 32ec2d7c3525] status=done    elapsed=274s          ← 真实 qrun 回测完成
产物: <workspace>/{qlib_res.csv, ret.pkl, miner_result.json}
metrics: ok=True IC=0.0187 / 0.0241（两轮）  净值曲线与成交明细齐全
LLM 侧: 生成了 MOM_5 / MOM_10 / MOM_20 三个因子，CoSTEER 评估 Final Decision 全为 SUCCESS
```

### 首跑暴露并已修掉的四个真问题

| # | 问题 | 现象 | 修法 |
|---|---|---|---|
| 1 | **DeepSeek key 失效** | `Authentication Fails, Your api key: ****b508 is invalid`（10 次重试后 RuntimeError） | 换成 LangAlpha `.env` 里那把可用的（实测 HTTP 200）；备份 `.env.bak-*` |
| 2 | **embedding 无可用后端** | 智谱 `embedding-3` → `429 余额不足`；本机 ollama runner 崩（`GGML_ASSERT(buf_dst)`，两个模型都崩）；HF 缓存里的 all-MiniLM 只有配置文件没有权重 | 自建 `bridge/embed_shim.py`：sentence-transformers + `BAAI/bge-small-zh-v1.5`（512 维，103MB，走 hf-mirror 下载），暴露 OpenAI 兼容 `/v1/embeddings`；RD-Agent 侧用 `EMBEDDING_MODEL=litellm_proxy/bge-small-zh-v1.5` + `LITELLM_PROXY_API_BASE=http://127.0.0.1:11999/v1`（注意 **11435 被别的程序占着**，换 11999） |
| 3 | **`job_status` 成功终态是 `done` 不是 `ok`** | 作业 42s 就跑完，轮询永不返回（"挂住"） | `TERMINAL = {"done","error","not_found"}`（`mcp_gateway.JobQueue` 的真实取值） |
| 4 | **metrics Series 必须有名字 `"0"`** | feedback 层 `pd.DataFrame(series).rename(columns={"0": ...})`：无名 Series 列名是**整数 0**，rename 匹配不上 → `KeyError: 'Current Result'` | `series.name = "0"`，并从 `qlib_res.csv` 读回设给 `exp.result`（与上游逐字节等价） |

### 剩下的唯一缺口：baseline 实验 —— ✅ 已打通

`feedback.py:72` 读 `sota_result = exp.based_experiments[-1].result` 作为 SOTA 对比。
上游 `QlibFactorRunner.develop()` 开头会先跑 **baseline 实验**（`conf_baseline.yaml` = 纯 Alpha20 基线）。
桥的第一版漏了这段 → baseline 的 `result` 是 `None` → 上游 `process_results` 里
`pd.DataFrame(None)` 没有 "SOTA Result" 列 → `KeyError: 'SOTA Result'`（报错完全指不到病因）。

**已实现（方案 A）**：
- `factor_miner/conf_baseline.yaml` —— 移植自 RD-Agent 的 `conf_baseline.yaml`（MIT），
  **不含 StaticDataLoader**（不读 `combined_factors_df.h5`，基线就是 Alpha20 本身），
  其余 model/dataset/record 与组合口径逐字一致以保证可比；
- `factor_backtest.py`：`BASELINE_CONF_TEMPLATE` + `baseline=True` 分支 + 抽出 `_execute_and_parse()`
  （**baseline 与组合回测共用第 4 步**，避免两条路分叉出两套指标）；
- `factor_worker.py`：`baseline` 开关（**沿用与因子轮相同的 profile/windows** —— 否则
  基线 csi300/2008-2018 与 smoke 轮 30 票/2019 不可比），`_render_windows_conf(template=...)`；
- `tools.py`：`factor_backtest` 新增 `baseline` 参数；
- 桥：`_ensure_baseline()` 真跑基线并写回 `baseline.result`（不再是报错占位）。

**部署提示（重要）**：miner 的代码是**烧进镜像**的（`docker-compose.override.yml` 未启用
`./factor-miner-mcp:/app` 那个 bind mount），所以本次是用 `docker cp` + `docker restart` 落地的。
**要让改动在重建后仍存在，必须 `docker compose build factor-miner && up -d factor-miner`**
（或启用 local override 的源码挂载）。

### ✅ 完整一轮的实测结果（2026-09-23）

```
步骤: direct_exp_gen → coding → running → feedback → record     5/5 步，7 分 30 秒
桥:   baseline 作业 892f1ff66cef status=done @76s
      因子轮作业 10a81c4cd268 status=done @324s
落盘: log/2026-09-23_01-33-00-045566/Loop_0/{direct_exp_gen,coding,running,feedback,record}
      以及 __session__/0（FactorRDLoop.load 可续跑）
成本: 整轮累计 $0.0148（单次调用 $0.00089）
```

**feedback 真的在做 SOTA 对比并给出进化方向**（这是 baseline 打通后才可能的）：
```json
{"Observations": "四因子组合 IC 0.018725 …",
 "Feedback for Hypothesis": "这些简单价量因子能提升表现的假设被推翻，组合结果不如 SOTA…",
 "New Hypothesis": "转而寻找刻画非线性关系的因子，例如量价微结构/行为模式…",
 "Replace Best Result": "no"}
```
→ 第一轮不替换 SOTA（正确判断），并提出了更有信息量的下一轮假设 —— **进化闭环成立**。

### 待核实 / 运维注意（诚实标注）

**① smoke 档 SigAna 指标重复（已第 3 次复现）**
多次 smoke 回测返回的 **IC=1.55121038889013e-17 / RankIC=NaN / ICIR=0.22337301446315402 逐位相同**，
而 PortAna 的 `annualized_return_with_cost` / `max_drawdown` 每次都不同（-0.263 / -0.289 / -0.258…）。
两次独立运行要到 15 位有效数字一致几乎不可能是巧合 → 高度怀疑 **SigAna（信号分析）指标并非来自本次 run**：
或 `read_exp_res` 在**共享 mlflow store** 里取到了同一个 recorder，或 smoke 小样本下该 label
（`Ref($close,-2)/Ref($close,-1)-1`）产生了退化信号 + 某个常量兜底。
**影响**：SOTA 对比用的正是 IC 一族指标 → 若为前者，feedback 的"是否优于 SOTA"就不可信。
**核法**：拿某个 job 自己的 `mlruns/<exp>/<run>/metrics` 与其返回的 metrics 逐项比对。

**② miner 容器会被自己的 cgroup OOM 杀掉（与本次集成无关的既有脆弱性）**
实测 2026-09-23 19:44:34 与 20:00:50 两次 `oom-kill: constraint=CONSTRAINT_MEMCG … task=python3, uid=10001`，
对应 `mcp-factor-miner` 的两次原地重启（`mem_limit=1536m`，`restarts=2`；容器 `created` 仍是 4 天前 → 未重建）。
这两次**不是**本次循环造成的（本轮 loop 跑在 01:33 UTC），但说明 miner 里任何"整读 405MB 面板"的重活
（如 `update_data`）都会打爆它。
**对本集成的影响**：桥依赖 miner 在线，重启窗口内提交会超时/被拒 → 调用方需重试；
**长期**应把重活继续推向执行器容器或给 miner 加内存。

**③ 隧道是硬依赖（跨机跑循环时）**
miner 的 50053 只绑在服务器 `127.0.0.1`，本机跑桥必须挂 SSH 隧道。一次性 `ssh -L` 会因 keepalive 超时
静默死掉（实测 exit 255 `Timeout, server not responding`，而服务器本身健康）。
→ 用带自动重连的守护（`/tmp/tunnel_50053.sh`，`ServerAliveInterval=20 ServerAliveCountMax=6 TCPKeepAlive=yes`）。

---

### 已知不确定项（不掩盖）

- `validate_qlib_features()` 走 `QlibCondaEnv`（conda 分支）；本次运行未触发。
- 每个 smoke 回测实际耗时 **274s**（比我自检的 42s 长），因为 LLM 生成的因子在面板上的计算量更大；
  跑 full profile 会更久（miner 侧 full 单次 218s 起）。

---

## L3 落库层（待做，半天）

1. **一行改动**（否则 RD-Agent 的因子会被静默降级成人工因子）：
   ```python
   # src/server/services/factor_library.py:43
   FACTOR_SOURCES = ("user", "agent", "sota", "athena", "rdagent")
   ```
2. **importer**：RD-Agent session → `factor_library` 行（幂等：`(user_id,name)` 唯一 + `code_hash`）：

| LangAlpha 列 | 来源 |
|---|---|
| `name` / `description` | `FactorTask.factor_name` / `factor_description` |
| `hypothesis` | `Hypothesis` 文本（表级 NOT NULL，缺了不许入库） |
| `code` | `sub_workspace.file_dict["factor.py"]` |
| `metrics` | 桥写回的 `qlib_res.csv`（JSONB） |
| `source` | `"rdagent"` |
| `status` | `"candidate"`（**绝不直接 promoted**） |

3. **run 台账**（借 QuantMind 的 `launcher + persistence` 分层）：建议一张
   `factor_mining_runs(user_id, run_id, status, loop_n, session_path, events JSONB, created_at)`，
   由 launcher 写、看板读；**不要**再自造第三套 run 簿记（athena 已有 `mining_runs`/`mining_events`，二选一）。

---

## L4 触发层（待做，1 天）

**推荐 A：注册 `rdagent` MCP server**（与现有 10 个域同构，athena agent / WeChat / ptc_agent 都能触发）

```
fastmcp 包一层：  run_mining(loop_n=1, profile="smoke") → FactorRDLoop(FACTOR_PROP_SETTING) → asyncio.run(loop.run(...))
注册到 /opt/mcp-hub/mcp_settings.json：
  { "rdagent": { "type": "streamable-http", "url": "http://127.0.0.1:50063/mcp", "enabled": true } }
```
（照 `factor-miner` 的样板：`streamable-http http://127.0.0.1:5005X/mcp`；端口建议 50063 避开现用段。）

**备选 B**：LangAlpha backend 直接 import `bridge` 起后台任务 —— 更少一跳，但把 LLM 循环塞进平台进程，
与平台的重启/升级节奏耦合，不推荐。

**不要**用 RD-Agent 自带的 Flask `server_ui` 当生产编排接口（面向 UI、默认绑 127.0.0.1、`/control` 只支持 stop）。

---

## L5 治理层

| 项 | 现状 | 建议 |
|---|---|---|
| 并发 | miner 重任务 **per-key 单槽**；失败/超时的 handler 不回收 | ① 调用方 busy 时核对台账；② 在 miner 加作业看门狗（超时即清槽） |
| 成本 | `evolving_n`（默认 10）× 内环 ≤10 轮 × 多次 LLM | 首跑 `--step_n 1`；`QLIB_FACTOR_EVOLVING_N` 调小；token 记账 |
| 质量 | `hypothesis NOT NULL` + 看板把假设渲染在代码之上 | 去重闸门（IC≥0.99）+ OOS 准入（衰减 >50% 不予 live） |
| 安全 | **LLM 生成的因子代码默认在宿主机裸跑**（`shell=True`，`python_bin="python"`） | `FACTOR_COSTEER_PYTHON_BIN` 指向受限解释器；终态复用 factor-miner 沙箱（AST 白名单 + rlimit） |
| 版本 | 稳定版 v0.8.0（2025-11）停更，main 领先约 10 个月（含安全加固 #1469） | **pin 具体 commit** 自建 wheel；只把 `rdagent.core.proposal` 当稳定 API |
| 跨机 session | 制品有 HMAC 签名（`ARTIFACT_SIGNING_KEY`） | 多机共享 session 时统一该 key |

---

## 部署形态与资源

| 位置 | 适合 | 约束 |
|---|---|---|
| **本机 M2** | ✅ L1+L2 已就绪（面板已预置、桥自检通过、`.venv` 有 rdagent/pandas） | 8GB 统一内存；`qrun` 在服务器上跑，所以**本机不吃回测内存**（这是桥的最大红利） |
| 服务器 | 轻外壳（只跑 LLM 循环 + HTTP 调 miner） | 4 vCPU / 7456 MB / 14 容器 2.5× 超卖；`avail ~3.9G` 时可以，重活不要并行 |
| 独立机器 | 想每天多轮 | ≥8 vCPU / 16GB |

**为什么桥能省内存**：回测在 miner 的执行器容器里跑（有 cgroup + `RLIMIT_AS` 护栏），
宿主机只跑 LLM 循环（百 MB 级）——社区那批 36–46GB OOM 的问题对我们不成立。

---

## 验收清单（逐项可勾）

- [x] `bridge.selftest` 通过：真回测 + 三个 key 齐 + `qlib_res.csv`/`ret.pkl` 写出
- [x] 数据目录预置，`get_data_folder_intro()` 不触发 Docker
- [x] miner 侧 full profile 能跑（218s，IC 0.0191/年化 +4.40%/MDD -19.69%）
- [x] **`QLIB_FACTOR_RUNNER=bridge.runner.FactorMinerRunner` 跑通完整一轮**（5/5 步，baseline+因子轮都走 miner，feedback 做出真实 SOTA 判断，$0.0148）
- [x] miner 侧 `baseline` 参数打通（纯 Alpha20，76s）
- [ ] `FACTOR_SOURCES` 加 `"rdagent"` + importer，看板能看到 `source=rdagent` 的候选因子
- [ ] `rdagent` MCP server 注册进 hub，athena/agent 能触发
- [ ] miner 重任务看门狗（超时清槽）
- [ ] **miner 改动正式重建进镜像**（当前是 `docker cp` 落地的临时部署）
- [ ] 核实 smoke 档 SigAna 指标重复的疑点（见「待核实」）
