# RD-Agent × Qlib → LangAlpha 集成设计

> 调研日期 2026-09-23。所有结论均已在本机/服务器实际核验，标注了证据来源；
> 凡属推断的地方都写明「推断」，未核实的写明「未核实」。
> 配套深度资料：`~/Documents/deepseek/qlib-research/qlib-data-format-research.md`（960 行，Qlib 源码级调研）

---

## 0. 结论摘要（TL;DR）

1. **「把 Qlib 集成进 LangAlpha」这件事已经做完了。** LangAlpha 的因子看板（`factor-board.md`）
   背后调的是 factor-miner MCP，而 factor-miner 的回测就是 **qlib 0.9.7 + `qrun`**；
   因子库表（migration 044）已经在存 qlib 口径的 tearsheet。缺的不是 qlib，是**挖掘回路（mining loop）**。
2. **RD-Agent 不需要整体搬进生产。** 它的价值是「LLM 假设 → 写因子代码 → 回测 → 反馈进化」这条循环的
   工程范式，而这条范式**已经被移植过两轮**（见 §1）。真正值得引入的是**它的循环外壳**，
   不是它的 Docker/conda 运行时。
3. **推荐的集成形态 = 「换回测链路」而非「加一个服务」**：用 RD-Agent 的
   `QLIB_FACTOR_*` 可插拔设置（`env_prefix="QLIB_FACTOR_"`，见 §3）把它的
   `qrun` 执行层替换成 **factor-miner 的回测链路**（走 miner MCP → 执行器容器，已跑着 qlib 0.9.7 + 846MB `.bin` + 内存护栏）。
   **不 fork 源码、不改一行 RD-Agent 代码**，产出的指标口径与生产完全一致（`with_cost`、`FactorEmptyError` 语义）。
4. **数据层零改造**（这是本次最有价值的发现）：`/opt/athena-mcp/qlib_data/cn_data` 已具备
   RD-Agent 要的一切 —— 6152 标的、`vwap` 6142 个、`factor` 6152 个、`csi300.txt` 在。§2.1 有证据表。
5. **不要把 RD-Agent 的整体运行时（Docker 版）放进那台 4vCPU/7.4G 的机器**：它历史上已有 4 次静默冻结，
   而 RD-Agent 的 `QlibDockerConf` 默认要 `shm_size: 16g` + GPU（§8.1）。生产机只跑「换回测链路」后的轻外壳，
   重活留在执行器容器/本地。

---

## 1. 先把前提摆正：现在有三条腿，且都不是「从零开始」

调研中最重要的发现不是 RD-Agent 本身，而是**这盘棋已经下了三手**：

| # | 腿 | 位置 | 状态（已核验） | 角色 |
|---|---|---|---|---|
| 1 | **athena Go FactorMiner** | `~/project/athena/internal/factor/miner/` | **已实现**：4246 行（`loop.go` 25KB、`costeer.go`、`sota.go`、`store_sqlite.go`、`remote_client.go`、`sidecar_backtest.go`、`sidecar_production.go`）；MCP 工具 `run_factor_mining` / `get_mining_runs` / `get_factor_library` | **大脑**（循环/假设/SOTA 簿记/LLM 记账） |
| 2 | **factor-miner-mcp** | `~/project/factor-miner-mcp`（服务器 `mcp-factor-miner` + `mcp-factor-executor`） | **已上线**：18 个工具、qlib 0.9.7、846MB `.bin`、qrun 独立容器、内存护栏 | **手**（沙箱执行 / qlib 回测 / 专业评估） |
| 3 | **RD-Agent** | `~/project/RD-Agent`（v0.8.0-31-g6762f84f） | **克隆了、没跑通**：见 §2.3 | **范式与参考实现** |

**关键联系**：athena 的 `remote_client.go:30` 写着 `baseURL 如 http://host:50053` ——
**腿 1 已经在用 MCP 调腿 2**。所以「集成 RD-Agent」不是接一个新世界，而是决定**谁当大脑**。

**移植痕迹（说明三者同源）**：factor-miner-mcp 里至少 6 处标注了 RD-Agent 出处（MIT）——

| factor-miner 文件 | 移植自 RD-Agent |
|---|---|
| `factor_eval.py:12` | `rdagent/components/coder/factor_coder/eva_utils.py` |
| `gen_data.py:9` | `scenarios/qlib/experiment/factor_data_template/generate.py` |
| `conf_combined_factors.yaml:3` | `scenarios/qlib/experiment/factor_template/conf_combined_factors.yaml` |
| `factor_backtest.py:22,65` | runner 语义 + `rdagent/utils/qlib.py` 的 `ALPHA20` |
| `sandbox.py:9` | 超时策略（120s vs RD-Agent 3600s） |
| `factor_worker.py:60` | 挖掘窗口 test 起点口径（2017-01-01） |

→ **推论：把它当作「第三代」来设计是错的；正确姿势是复用腿 1/2 已有的一切，只补 RD-Agent 的循环外壳。**

---

## 2. 已核实的事实

### 2.1 数据层：零改造（决定性证据）

在 `mcp-factor-executor` 容器里实测（`/qlib_data/cn_data`）：

| 项 | 实测值 | RD-Agent/Alpha158 的要求 | 结论 |
|---|---|---|---|
| 标的数 | **6152** | — | ✅ |
| `vwap.day.bin` | **6142** | **硬需求**（Alpha360 硬编码 60 个 VWAP 特征；Alpha158 默认 config 含 VWAP） | ✅ 缺的 10 个是指数类 |
| `factor.day.bin` | 6152 | 可选（语义=`$close/$factor`） | ✅ |
| `adjclose.day.bin` | 6142 | 可选 | ✅ |
| `calendars/` | 存在 | 必须有 | ✅ |
| `instruments/all.txt` | 6152 行 | — | ✅ |
| **`instruments/csi300.txt`** | **存在（16198 行成员区间）** | **`dump_all` 只产 `all.txt`，缺失是接自有数据第一坑** | ✅ 已有人补齐 |
| 总大小 | **846M** | — | ✅ |

**宿主挂载**（`docker inspect mcp-factor-executor`）：

```
/opt/athena-mcp/qlib_data        -> /qlib_data        (rdonly；⚠️ 必须挂祖父目录，日更 atomic_swap 会整体 rename)
/opt/athena-mcp/data/factor_mining -> /data/factor_mining  (daily_pv_all.h5 / daily_pv_debug.h5)
/opt/mcp-suite/backtests         -> /work             (与 miner 同挂，否则提交被拒)
```

→ **RD-Agent 只要挂同一个 `/opt/athena-mcp/qlib_data`，读的就是生产同一份数据**（也是同一份日历，
避免了「交易日历必须 dump 前定死」那个不可逆的坑）。

### 2.2 执行层：qlib 已经在跑

- 执行器与 miner 容器内 `qlib 0.9.7`（实测 `import qlib` 成功）。
- `qrun` 走独立容器 `mcp-factor-executor`，内存护栏：容器 `mem_limit 2600m` + `EXECUTOR_MEM_LIMIT_MB=2300`（`RLIMIT_AS`）。
- 生产实测（`README.md` §"qrun 要多少内存"）：full profile（csi300 × 2008→今 × Alpha158 + LGBM）**cgroup 峰值 3581 MiB**；
  而 `RLIMIT_AS=5120MiB` 会 `MemoryError` —— **地址空间（VA）远高于 RSS，新预算必须按 VA 给**。
- 评估链：`factor_evaluate`（沙箱跑代码 + alphalens 口径 tearsheet + 单调性/IC 半衰期/IC t 值）已上线。
- **接口可达性（集成硬约束，实测）**：执行器 `50054` **未发布到宿主机**（只有 docker 网络内的
  `http://factor-executor:50054`；miner 的 `FACTOR_EXECUTOR_URL` 正是这个值），宿主 `curl 127.0.0.1:50054` → HTTP 000。
  而 **miner MCP `127.0.0.1:50053/mcp` 宿主可达**（实测 18 tools）→ 外部集成一律走 miner，不走执行器。

### 2.3 RD-Agent 本地现状：跑过、但死在环境

已核验（`~/project/RD-Agent`）：

| 项 | 实测 |
|---|---|
| 版本 | `v0.8.0-31-g6762f84f`（Python ≥3.10） |
| `.venv` | 1.3G，**装了 rdagent，但没有 qlib**（`import qlib` → ModuleNotFoundError） |
| `.env` | 已配 `CHAT_MODEL=deepseek/deepseek-chat` + DeepSeek key（注释「复用 athena 的 key」）、智谱 embedding、`MODEL_CoSTEER_ENV_TYPE=docker`、`CONDA_DEFAULT_ENV=rdagent` |
| **Docker** | **守护进程没在跑**（`Cannot connect to the Docker daemon at unix:///Users/hjx/.docker/run/docker.sock`） |
| 本机 qlib 数据 | `~/.qlib/qlib_data/cn_data` **存在** |
| 跑过几次 | `log/` 下 **15 个** session（2026-08-25 11:16→12:25）、`git_ignore_folder/RD-Agent_workspace/` 9 个会话目录 |
| **失败证据** | 解出 `debug_tpl` pkl：`{'context': {'stdout': '/bin/sh: timeout: command not found'}}` |
| 进展 | 会话目录里只有 `runtime_info.py`，**没产出 `factor.py`/`conf.yaml`** → 卡在环境准备，没进到因子生成 |

→ **上次的结论**：不是 RD-Agent 不好用，是**macOS 缺 GNU `timeout` + Docker 没起 + venv 缺 qlib** 三件事一起挡着。
`.env` 注释「实验少跑几轮，先验证链路」说明当时意图就是先验链路，没走通。

---

## 3. RD-Agent 的可插拔面（集成的地基）

这是本次调研中**最关键的工程发现**：整条因子循环的每个组件都是**点分路径字符串**，
由 `import_class()` 动态导入（`rdagent/utils/__init__.py:53` → `importlib.import_module`，
`rdagent/components/workflow/rd_loop.py:33-42` 逐个 `import_class(PROP_SETTING.*)()`）。

`FactorBasePropSetting`（`rdagent/app/qlib_rd_loop/conf.py:52-71`）**带 `env_prefix="QLIB_FACTOR_"`**：

| 设置字段 | 默认实现 | 环境变量覆盖 |
|---|---|---|
| `scen` | `scenarios.qlib.experiment.factor_experiment.QlibFactorScenario` | `QLIB_FACTOR_SCEN` |
| `hypothesis_gen` | `...proposal.factor_proposal.QlibFactorHypothesisGen` | `QLIB_FACTOR_HYPOTHESIS_GEN` |
| `hypothesis2experiment` | `...proposal.factor_proposal.QlibFactorHypothesis2Experiment` | `QLIB_FACTOR_HYPOTHESIS2EXPERIMENT` |
| `coder` | `...developer.factor_coder.QlibFactorCoSTEER` | `QLIB_FACTOR_CODER` |
| **`runner`** | **`...developer.factor_runner.QlibFactorRunner`** | **`QLIB_FACTOR_RUNNER`** |
| `summarizer` | `...developer.feedback.QlibFactorExperiment2Feedback` | `QLIB_FACTOR_SUMMARIZER` |
| `evolving_n` | `10` | `QLIB_FACTOR_EVOLVING_N` |
| `train_start/end` … | `2008-01-01` / `2014-12-31` | `QLIB_FACTOR_TRAIN_START` … |

→ **可以完全不动 RD-Agent 源码，用环境变量把任意一环换成我们自己的类。**

### 3.1 三层注入点（由浅入深，按需选）

**第 1 层：换执行环境（最省事）** —— `QlibFBWorkspace.execute()`
（`scenarios/qlib/experiment/workspace.py:18-31`）：

```python
if MODEL_COSTEER_SETTINGS.env_type == "docker":
    qtde = QTDockerEnv()                 # QlibDockerConf: image=local_qlib:latest
elif MODEL_COSTEER_SETTINGS.env_type == "conda":
    qtde = QlibCondaEnv(conf=QlibCondaConf())   # conda_env_name="rdagent4qlib"
else:
    logger.error(f"Unknown env_type: ..."); return None, "Unknown environment type"
qtde.prepare()
execute_qlib_log = qtde.check_output(local_path=str(self.workspace_path),
                                     entry=f"qrun {qlib_config_name}", env=run_env)
execute_log = qtde.check_output(local_path=str(self.workspace_path),
                                entry="python read_exp_res.py", env=run_env)
```

**只有 docker / conda 两条硬编码分支，都没有 qlib 时直接返回 `None`** —— 这是我们不想要的。

> **纠正（源码级复核）**：`ModelCoSTEERSettings.env_type` 的**代码默认值是 `"conda"`，不是 `"docker"`**
> （`components/coder/model_coder/conf.py`）。README 说「most scenarios 必须先装 Docker」是因为
> `health_check` 会探测它、且多数场景确实用它；他们本地 `.env` 则显式写了 `docker`。
>
> 好消息：`MODEL_CoSTEER_ENV_TYPE=conda` 就能绕开 Docker 跑 qrun（与 athena 设计文档
> 「关键决策：qlib 跑在 py-sidecar venv 里，不用 docker」的判断同向）。
> **但有两处「绕不开」，P1 必须处理掉**：
> 1. `scenarios/qlib/experiment/utils.py::generate_data_folder_from_qlib()` **无条件** `QTDockerEnv()`
>    生成因子源码数据目录（`daily_pv.h5`）→ 首次运行若 `git_ignore_folder/factor_implementation_source_data(_debug)`
>    不存在就必须有 Docker。**绕过办法：预先手工放好这两个目录（`daily_pv.h5` + `README.md`）** ——
>    我们手上正好有 `daily_pv_all.h5` / `daily_pv_debug.h5`（`/opt/athena-mcp/data/factor_mining`）。
> 2. `components/coder/factor_coder/factor.py::FactorFBWorkspace.execute()` 用**裸 `subprocess`** 在宿主机
>    当前 Python 环境执行 LLM 生成的因子代码（`python_bin` 默认 `"python"`、`shell=True`）——**无任何隔离**。
>    → 这是安全红线（§8.9），也是复用 factor-miner 沙箱的第 4 个理由。

**第 2 层：换 `qrun` 的物理去处（推荐）** —— 自定义 `Env` 子类。基类契约：
`rdagent/utils/env.py:164`(`EnvConf`) / `:251`(`Env`) / `:303-311`：

```python
def check_output(self, entry=None, local_path=".", env=None,
                 running_extra_volume=MappingProxyType({}),
                 cache_key_extra_func=None, cache_files_to_extract=None) -> str
```

`QlibDockerConf` 的真实配置（`utils/env.py:1010-1030`，可被 `QLIB_DOCKER_*` 覆盖）：
`build_from_dockerfile=True`、`dockerfile_folder_path=scenarios/qlib/docker`、
`image="local_qlib:latest"`、`extra_volumes={~/.qlib: /root/.qlib}`、**`shm_size="16g"`**、**`enable_gpu=True`**。

**第 3 层：换整条 runner** —— `FACTOR_PROP_SETTING.runner`（`QlibFactorRunner`，`factor_runner.py:25`，
继承 `CachedRunner[QlibFactorExperiment]`）。实验对象在 `factor_proposal.py:111`
（`QlibFactorHypothesis2Experiment.convert_response`）里构造：
`QlibFactorExperiment(tasks, hypothesis=hypothesis)`，其 `__init__`
（`factor_experiment.py:22`）绑定 `self.experiment_workspace = QlibFBWorkspace(template_folder_path=.../factor_template)`。

→ 注入链完整：`hypothesis2experiment`（造实验）→ `QlibFactorExperiment.__init__`（绑 workspace）→
`workspace.execute()`（跑 qrun）。**任何一层都能用点分路径替换。**

### 3.2 编程入口（无需 shell 子进程）

```python
# rdagent/app/qlib_rd_loop/factor.py:17,54-62
class FactorRDLoop(RDLoop):
    skip_loop_error = (FactorEmptyError, CoderError)   # ← 与 factor-miner 的失败语义一致
factor_loop = FactorRDLoop(FACTOR_PROP_SETTING)
factor_loop._init_base_features(base_features_path)
asyncio.run(factor_loop.run(step_n=step_n, loop_n=loop_n, all_duration=all_duration))
```

- 支持**会话续跑**：`FactorRDLoop.load(path, checkout=checkout)`。
- CLI 等价物：`dotenv run -- python rdagent/app/qlib_rd_loop/factor.py $LOG_PATH/__session__/1/0_propose --step_n 1`；
  console script `rdagent = rdagent.app.cli:app`。

→ 可以被 MCP server 或 LangAlpha 后台任务**直接 import 调用**，不需要起独立服务。

---

## 4. Qlib 侧关键事实与纠偏

来自配套调研（源码级，`microsoft/qlib@be725493`；RD-Agent 锁定 qlib commit `2fb9380b34…`）+
本地实测。**以下 4 条纠正了常见误解，直接影响集成设计**：

1. **`qlib.data.dataset.QLibData` 不存在**（`__all__ = ["Optional", "Dataset", "DatasetH"]`）。
2. **`dump_bin.py` 不校验列名** —— 默认把除 `date`/`symbol` 外**所有列**都 dump；
   所谓「列名要求」来自下游因子库，不是 dump 脚本。唯一硬需求是 `date`（缺则 calendar 为空，**所有 feature 被静默 skip**）。
3. **`vwap` 是硬需求**（Alpha360 硬编码 60 个 VWAP 特征无法关闭；缺 `vwap.day.bin` 抛
   `ValueError: feature not exists`，**不是 NaN 填充**）。→ 我们的数据 ✅（6142/6152）。**`factor` 反而不强制。**
4. **`qrun` 的 `mlruns` 落在 CWD**（`qlib/cli/run.py`），不是 YAML 所在目录 —— 决定我们的工作目录布局。

**另外两条对集成有实际影响**：
- **HDF5 可直喂 qlib**：`qlib.utils.load_dataset` 原生支持 `.h5`，`StaticDataLoader._maybe_load_raw_data` 的 dict 分支会调它
  → 做**因子挖掘**可以完全不碰 `.bin`；只有**回测（`Exchange` 需要 calendar）**才必须 `.bin`。
  而 RD-Agent 的 `daily_pv_all.h5` **正是从 `.bin` 转出来的**（`generate.py` 用 `D.features()`），
  我们这边的 `factor_miner/gen_data.py` 就是它的移植版 —— 「HDF5→qlib」恰是 RD-Agent 数据流的**逆操作**。
- **`.bin` 是「日历下标 → 字节偏移」的纯位置映射**：`fp.seek(4*(i-start_index)+4)`，中间非交易日 NaN 占位
  → **append 便宜、回填历史极贵，日历必须在 dump 前定死**。这解释了为什么绝不能给 RD-Agent 单独喂一份数据。

---

## 5. 三种集成形态与决策

| | **A. 产物导入型** | **B. 换执行器型（推荐）** | **C. 全量运行时型** |
|---|---|---|---|
| 做法 | RD-Agent 在本地/别处跑，产出的 factor.py + 假设 + 指标**导入** LangAlpha 因子库 | RD-Agent 循环留用，`qrun` 换成 **factor-miner 执行器**（HTTP）；循环可跑在生产机或本地 | 原样部署 RD-Agent（Docker/conda 全套）到服务器，接 LangAlpha |
| 改动量 | 极小（+`source='rdagent'` + 一个 importer） | 中（一个 `Env` 子类 ~60-120 行，零 fork） | 大（镜像构建/拉取、conda、内存） |
| 指标口径 | 与生产一致（走 miner） | **与生产完全一致**（同一个 executor） | 多一套口径，**可能静默偏掉** |
| 资源风险 | 0（不占生产机） | 低（只多一个 LLM 循环进程） | **高**：`shm_size 16g` + GPU 默认 + 镜像构建 |
| 数据 | 复用 | **复用同一份 `/qlib_data`（同一日历）** | 需另配数据，易与生产漂移 |
| 落地速度 | 半天 | 1-2 天 | 不确定（受 Docker Hub/内存影响） |
| 适合 | 先验证「RD-Agent 的因子值不值得进库」 | **长期形态** | ❌ 不建议 |

**决策：A 作为 P0 打通落点 → B 作为终态。C 排除**，理由：① 生产机 4vCPU/7.4G 已 14 容器超卖并有 4 次静默冻结史；
② `QlibDockerConf` 默认要 16g shm + GPU；③ 第二套 qlib 数据必然与生产的日历/字段漂移，
而 `.bin` 日历不可回填 —— 这是无法事后修复的一类错误。

---

## 6. 推荐方案（分阶段）

### P0 — 落点打通（半天，零风险）

**目标**：让 RD-Agent 的产出有一条**正规入库通道**，先不碰循环运行时。

1. `src/server/services/factor_library.py:43` 的 source 白名单加一个值：
   ```python
   FACTOR_SOURCES = ("user", "agent", "sota", "athena", "rdagent")
   ```
   （`source` 列已存在，看板已按 source 渲染信任度；`save_factor()` 会把不在白名单的值静默降级为 `"user"`
   —— 所以不加这一行，RD-Agent 的因子会被**冒充成人工因子**，这是必须改的第一行。）
2. 新增一个导入器（CLI 或 `POST /api/v1/factors/import`），把 RD-Agent session 目录映射成因子行：
   | LangAlpha 字段 | RD-Agent 来源 |
   |---|---|
   | `name` / `description` | factor task 名 / 描述（`hypothesis2experiment` 产物） |
   | `hypothesis` | `Hypothesis` 文本（**NOT NULL**，表级强制经济假设） |
   | `code` | `factor.py` 全文 |
   | `metrics` | `qlib_res.csv` / `ret.pkl`（`read_exp_res.py` 产出）+ 正则抓 stdout 的 `Epoch\d+: train -…, valid -…` |
   | `source` | `"rdagent"` |
   | `status` | `"candidate"`（**绝不直接 promoted**） |
3. 幂等：`(user_id, name)` 唯一 + `code_hash`（表里已有），重复导入走 update 而非新建。

**验收**：一条 RD-Agent session → 看板出现该因子 → 点「评估」走 miner 出 tearsheet → 与 RD-Agent 自带指标量级一致。

### P1 — 换执行器（1-2 天，核心工作）

**目标**：让 RD-Agent 的循环用**生产的 qlib 执行器**跑回测，不再需要 Docker/conda/本地 qlib。

最小实现（零 fork）—— 一个 `Env` 子类把 `qrun` 转成对 **miner MCP** 的调用：

> ⚠️ **必须走 miner MCP（50053），不是执行器（50054）**：实测执行器的 50054 **没有发布到宿主机**
> （`docker ps` 只显示容器内 `50053/tcp`；宿主 `curl 127.0.0.1:50054` → HTTP 000 不通），
> 只有同 docker 网络的容器能用 `http://factor-executor:50054`（miner 的 env 正是这个值）。
> 而 miner MCP 是宿主可达的（`127.0.0.1:50053/mcp`，实测 18 tools）。
> 走 miner 还额外白拿三样：**异步作业机制**（`ASYNC_TOOLS` + `job_status`，回测动辄几分钟）、
> **`/work` 同挂校验**（路径不一致会被明确拒绝而不是静默偏掉）、**面板与 qlib 数据同源校验**。

```python
# bridge/factor_miner_env.py（新文件，不动 RD-Agent 源码）
from rdagent.utils.env import Env, EnvConf

class FactorMinerConf(EnvConf):
    default_entry: str = "qrun conf.yaml"
    miner_mcp_url: str = "http://127.0.0.1:50053/mcp"   # ← miner MCP，非执行器
    poll_interval: float = 5.0

class FactorMinerEnv(Env[FactorMinerConf]):
    def prepare(self) -> None:
        """探活 miner + 校验 provider_uri（miner 侧会校验面板与 qlib 数据同源）。"""
        ...
    def run(self, entry=None, local_path=".", env=None, **kw):
        # entry == "qrun conf.yaml"        → tools/call factor_backtest（异步）→ 轮询 job_status
        # entry == "python read_exp_res.py" → 取回 metrics + 净值曲线
        ...
```

注入方式（任选，都不改源码）：
```bash
# 方式 1：换 runner（推荐，语义最干净）
QLIB_FACTOR_RUNNER=bridge.runner.FactorMinerRunner   # 继承 QlibFactorRunner，只换 execute
# 方式 2：先绕开 Docker 验证链路可用性
MODEL_CoSTEER_ENV_TYPE=conda   # + conda env rdagent4qlib
```

**必须保住的三个语义**（否则结果不可比）：
1. 指标统一 `with_cost`（`factor_backtest.py:17` 已修正 RD-Agent trace 模板的 `without_cost` 内部不一致）；
2. `FactorEmptyError`（新因子与 SOTA 全部 IC≥0.99 被丢弃）→ Go 侧记 `decision=false`，不杀循环；
3. **SOTA 库每轮全量重算**走 miner 的执行缓存（`ic_hash` 命中跳过），否则 SOTA 增大后每轮成本线性上升。

### P2 — LangAlpha 侧产品化（2-3 天）

- **挖掘 run 的可见性**：LangAlpha 目前只有「单因子评估」，没有「多轮挖掘」。两条路：
  - 读 athena 的 `get_mining_runs`（MCP 已存在）→ 看板加一个 Mining tab（**零新表**，最快）；
  - 或在 LangAlpha 建 `factor_mining_runs`（`user_id` 外键 + `status` + `round_n` + `events JSONB`），
    由 LangAlpha 自己驱动 RD-Agent 循环。
  → 建议先读 athena 的（避免第三套 run 簿记），只有当 LangAlpha 要**自己跑**循环时才建表。
- **触发面**：MCPHub 注册新 server（照现有 pattern `streamable-http http://127.0.0.1:5005X/mcp`，
  当前已注册 10 个，含 `factor-miner` `http://127.0.0.1:50053/mcp`，实测 18 tools 可用）。
  这样 athena 的 agent、WeChat 机器人、ptc_agent 都能触发挖矿 —— 与现有 `run_factor_mining` 并列而非替代。

### P3 — 治理（持续）

- LLM 成本记账（RD-Agent 侧走 litellm → DeepSeek；LangAlpha 侧已有 token 用量工具）。
- 去重闸门（IC≥0.99）、OOS 准入（`DESIGN-FACTOR-MINER.md` §6：2021-01 至今纯样本外，
  衰减 >50% 不予 live）。
- 黑名单（同名跨轮累计失败 20 次永久跳过）。

---

## 7. 部署位置与资源预算

| 位置 | 适合 | 约束 |
|---|---|---|
| **服务器（47.90.253.85）** | **P1「换执行器」后的轻外壳**（只有 LLM 循环 + HTTP 调用） | 4 vCPU / 7456 MB / 18G free；**已 14 容器、限额和 22,272 MB vs 7456 MB（3× 超卖）**；executor 已限 2600m/RLIMIT 2300 |
| **本机 M2（8GB）** | 开发/RD-Agent 原样跑（Docker 或 conda） | 需先修三件事（见下）；`qrun` 峰值 3.6GB VA → 本机跑 full profile 也紧 |
| **独立机器** | 想长期跑多轮 `evolving_n=10` 的完整循环 | 需要 ≥8 vCPU / 16GB 才有余量（与「50 人沙箱服务器」那个话题同一决策） |
| Daytona 沙箱 | ❌ 不适合 | 免费版 1 vCPU/1GB，`DaytonaProcessExecutionTimeoutError`；放不下 qlib 846MB 数据 + 3.6GB 回测 |

**若要本机跑通 RD-Agent，前置清单（按顺序修，全部已核验为当前阻塞项）**：
1. `brew install coreutils`（或 `alias timeout=gtimeout`）—— 上次失败原因就是 `/bin/sh: timeout: command not found`；
2. 起 Docker Desktop（`MODEL_CoSTEER_ENV_TYPE=docker`）**或**改 `conda` 并建 env `rdagent4qlib`
   （注意 `.venv` 里**没有 qlib**，conda 路线也得装）；
3. 若走 Docker：`QLIB_DOCKER_SHM_SIZE=2g`、`QLIB_DOCKER_ENABLE_GPU=False`（默认 16g/GPU 是本机跑不动的直接原因）；
4. 数据：本机 `~/.qlib/qlib_data/cn_data` 已存在，会被 `extra_volumes` 自动挂到 `/root/.qlib/`。

---

## 8. 风险登记

| # | 风险 | 证据/影响 | 对策 |
|---|---|---|---|
| 8.1 | **Docker 默认配置在小机器上必然失败** | `QlibDockerConf.shm_size="16g"`、`enable_gpu=True`、`build_from_dockerfile=True` | 用 `QLIB_DOCKER_*` 覆盖；或直接走 P1 换执行器（推荐） |
| 8.2 | **qlib 版本漂移** | 执行器 `qlib 0.9.7`；RD-Agent 锁 commit `2fb9380b34`；PyPI 元数据（`pandas>=0.24`）比 main 分支旧 | **回测必须发生在同一环境**（P1 的另一动机）；不要在 LangAlpha 侧再装一份 qlib |
| 8.3 | 第二套数据导致日历不一致 | `.bin` 日历不可回填（§4） | 只挂 `/opt/athena-mcp/qlib_data`，不复制 |
| 8.4 | macOS 无 GNU `timeout` | 上次真实失败原因 | `brew install coreutils` |
| 8.5 | `mlflow<3.13` pin | 3.13 关闭 filesystem tracking → `qrun` recorder 静默失效 | 执行器已处理（`MLFLOW_ALLOW_FILE_STORE`，见 commit `df5d886`）；新环境不要升 mlflow |
| 8.6 | LLM 成本 | `evolving_n=10` × 内环 ≤10 轮 × 假设/编码/反馈多次调用 | 先 `--step_n 1` 验链路（上次 `.env` 就是这个意图）；成本随 token 记账 |
| 8.7 | 因子质量（数据挖掘） | 表级强制 `hypothesis NOT NULL`；看板把假设渲染在代码之上 | 保持 `candidate` 起步 + OOS 人工准入 |
| 8.8 | 三套挖掘簿记并存 | 腿 1（Go `mining_events`）、腿 2、RD-Agent session | **P2 决策**：只认一套 run 台账（建议读 athena 的 `get_mining_runs`） |
| 8.9 | **LLM 生成的因子代码在宿主裸跑（安全红线）** | `FactorFBWorkspace.execute()` = `subprocess.check_output(f"{python_bin} {path}", shell=True)`，`python_bin` 默认 `"python"`，**不在任何容器/conda 隔离里**（v2 任务另有模板路径） | 设 `FACTOR_COSTEER_PYTHON_BIN` 指向受限解释器；终态复用 factor-miner 沙箱（已有 AST 白名单 + rlimit） |
| 8.10 | **社区实测爆内存，官方未答复** | #1327「关于并发数和内存占用」：0.8 版 `fin_factor`/`fin_quant` 吃满内存、**122 线程**，评论「36GB/46GB 仍卡死」；#1262 卡在 `process_factor_data:50`（CPU 归零、内存高企），维护者仅答「建议升级」，3 人复现；**均 open** | 显式 `STEP_SEMAPHORE=1`（唯一官方调节阀）+ `MULTI_PROC_N=1`；绝不用默认配置跑共享机 |
| 8.11 | **默认 bandit 调度残缺（官方 bug）** | #1451：`bandit.py` 里 ARR 的 metric key 多一个**尾空格** → ARR(权重 0.25) 与 sharpe(0.20) 奖励**永远为 0**（PR #1479 待合） | 别指望 bandit 选方向；固定权重或自打补丁 |
| 8.12 | **稳定版停更、main 领先约 10 个月** | PyPI/最新 release = **v0.8.0（2025-11-03）**；main 已有安全加固（#1469, 2026-09）与新场景，仅有预发布 `0.8.1.dev24` | 锁具体 commit 自建 wheel；只把 `rdagent.core.proposal` 当稳定 API |
| 8.13 | 反馈层 3 个 metric key 硬编码 | `developer/feedback.py`：`IMPORTANT_METRICS = ["IC", "1day.excess_return_with_cost.annualized_return", "1day.excess_return_with_cost.max_drawdown"]`，缺任一即 `KeyError` | 执行器必须产出这三个精确 key（我们的 qrun conf 与 RD-Agent 同源，天然一致）；**不要去换 summarizer** |

---

## 9. 最小验收路径（可执行）

```bash
# 0) 前置：确认执行器活着 + qlib 数据在位（约 10 秒）
ssh root@47.90.253.85 'docker exec mcp-factor-executor sh -lc \
  "python -c \"import qlib;print(qlib.__version__)\"; ls /qlib_data/cn_data/instruments/csi300.txt"'

# 1) P0：一条 RD-Agent session → LangAlpha 因子库（不跑循环，用手工构造的 factor.py）
#    验收：看板可见 + source=rdagent + status=candidate

# 2) P0：点「评估」，比对 miner tearsheet 与 RD-Agent 自带指标（IC/年化/回撤量级一致）

# 3) P1：把回测执行换成生产 miner（走 MCP，非执行器），跑单轮（先 step_n=1 控成本）
cd ~/project/RD-Agent
QLIB_FACTOR_RUNNER=bridge.runner.FactorMinerRunner \
FACTOR_MINER_MCP_URL=http://127.0.0.1:50053/mcp \
FACTOR_COSTEER_PYTHON_BIN=/path/to/restricted/python \
  dotenv run -- .venv/bin/python rdagent/app/qlib_rd_loop/factor.py --path <session> --step_n 1
# 注 1：必须 `dotenv run --`！.env 只在 rdagent/app/cli.py 里 load_dotenv，
#        直接跑脚本不加载 → 拿不到 API key（官方 factor.py 的 docstring 也是这么写的）
# 注 2：换掉 runner 后 QlibFBWorkspace.execute() 不再被走到，MODEL_CoSTEER_ENV_TYPE 无所谓
#        （源码只认 docker/conda，其他值会 "Unknown env_type" 并返回 None —— 别写 local）
# 注 3：FACTOR_COSTEER_PYTHON_BIN 至少把「裸 subprocess 跑 LLM 代码」指向受限解释器（见 §8.9）
#    验收：无 Docker、无 conda；miner 侧出现该回测作业；产物入库

# 4) P2：看板 Mining tab 能看到这轮 run 的 events
```

**注意**：`--step_n 1` 只跑一轮（`loop_n` 控制总轮数），这是控成本的第一道闸门。

---

## 10. 待你决策的四个问题

1. **大脑归属**：RD-Agent 当大脑（P1 全量走通），还是继续 athena Go FactorMiner 当大脑、RD-Agent 只做「导入源」？
   （现状：腿 1 已实现 4246 行且在用 MCP 调腿 2 —— 换大脑的性价比需要你判断。）
2. **跑在哪**：服务器（轻外壳）/ 本机 M2（重、但零生产风险）/ 新机器？
3. **要不要建 LangAlpha 自己的 mining run 表**，还是读 athena 的 `get_mining_runs`？
4. **P0 是否现在就做**（改 `FACTOR_SOURCES` + importer，半天、零风险、可随时回滚）？

---

## 11. 官方与社区怎么玩（生态实况）

### 11.1 官方玩法：一台 Linux + Docker 机器上的「场景化 CLI」

官方全部用法就是这一串命令（`README` §Run the Application，已逐条核验）：

| 命令 | 场景 | 备注 |
|---|---|---|
| `rdagent fin_quant` | **因子 + 模型联合演化 = RD-Agent(Q)** | 官方主推；对应论文配置（含 `GeneralPTNN`） |
| `rdagent fin_factor` | 只挖因子 | **factor-miner-mcp 移植的就是这条** |
| `rdagent fin_model` | 只做模型演化 | |
| `rdagent fin_factor_report --report-folder=<dir>` | **从财报 PDF 里抽因子** | 官方给了资源包 `SunsetWolf/rdagent_resource` releases |
| `rdagent general_model <paper URL>` | 从论文实现模型 | `rdagent general_model "https://arxiv.org/pdf/2210.09789"` |
| `rdagent data_science --competition <name>` | Kaggle/DS 场景 | |
| `rdagent llm_finetune --base-model Qwen/Qwen2.5-7B-Instruct` | LLM 微调场景 | ICML 2026 |
| `rdagent ui --port 19899 --log-dir log/` | Streamlit 日志 UI | `--data-science` 看 DS 场景 |
| `rdagent server_ui --port 19899` | Flask Web UI（`web/` 前端 `npm run build:flask`） | **面向 UI，不是生产编排 API**：默认绑 127.0.0.1、`/control` 只支持 stop |
| `rdagent health_check` | 检查 Docker + UI 端口 | `--no-check-env --no-check-docker` 可跳过 |

> 官方**没有** `rdagent qlib`，也**没有** `rdagent server`（这两个常见误记要避免）。
> 官方 Live Demo：`https://rdagent.azurewebsites.net/`。

**官方标准开局**（`docs/installation_and_configuration.rst` + README）：
`conda create -n rdagent python=3.10` → `pip install rdagent`（或源码 `make dev`）→
`rdagent health_check` → 写 `.env`（**DeepSeek 是官方文档化的配方**：`CHAT_MODEL=deepseek/deepseek-chat`
+ embedding 走 `litellm_proxy/BAAI/bge-m3`，因为 DeepSeek 无 embedding 模型；推理模型加
`REASONING_THINK_RM=True`）→ `rdagent fin_quant` → 另开 `rdagent ui` 看日志。

**官方 qlib 场景的默认口径**（`docs/scens/quant_agent_fin.rst`）：`provider_uri=~/.qlib/qlib_data/cn_data`、
`market=csi300`、`benchmark=SH000300`、数据 `2008-01-01→2022-08-01`、fit `2008-2014`、
train/valid/test = `2008-2014 / 2015-2016 / 2017-01-01→2020-08-01`、特征 = `Alpha158DL` +
`StaticDataLoader(combined_factors_df.parquet)`、模型 = **`GeneralPTNN`（PyTorch NN，n_epochs 100 / lr 2e-4 /
batch 256 / GPU 0）**、策略 `TopkDropoutStrategy`(top50, drop 5)、初始资金 1 亿。
→ **与我们的差异**：我们 conf 用 **LightGBM** 且 `test_end=null`（生产有效优先），官方是 PTNN + 2020-08-01（口径可比优先）。

**官方论文成绩**（arXiv `2505.15155`，NeurIPS 2025，逐字核对）：CSI300 + o3-mini ——
**IC 0.0532 / ICIR 0.4278 / RankIC 0.0495 / ARR 14.21% / IR 1.7382 / MDD -7.42%**；
对照 Alpha158 ARR 5.70%、Alpha360 4.38%；CSI500 IR 2.1721；**成本 <$10、12 小时跑 44 loop（≈16 min/loop，约半数 loop 无效）**。

### 11.2 社区玩法：四种典型姿势

| 姿势 | 代表项目/文章 | 做法 | 对我们的参考 |
|---|---|---|---|
| **中文部署指南** | `franxyang/RD-Agent-ETF` → `DEPLOYMENT_GUIDE_CN.md`（针对 0.7.0） | ETF 场景从零部署全流程 | 最「照着做」的模板；但版本停在 0.7.0 |
| **换掉 LLM 后端** | `rozwer/Qlib-with-Claudex` | 用 Claude Code / Codex CLI 替掉 OpenAI | 我们已用官方 DeepSeek 配方，无需替换 |
| **拼平台** | `qusong0627/QuantMind`、`MrRobotop/Quant-Alpha-Factory` | Qlib 因子集 + **RD-Agent 因子演化** + TradingAgents 多智能体 组装成一个平台 | **与我们同构**（LangAlpha + factor-miner + athena），可直接借鉴其边界划分 |
| **接实盘/第三方数据** | `mengjihao/qlib-rdagent-tqsdk` | 用 TQSDK 供数喂 qlib | 数据源替换思路（我们已在用 `investment_data` 社区源） |
| **教程内容** | 步子哥/智柴网《量化交易 RD-Agent/Qlib 实战指南》、CSDN《RD-Agent(Q) 实战指南：5 步搭建》、匡醍量化、MSR Asia 官方文章 | 5 步搭建 | 说明社区对「上手成本」的共识 |

### 11.3 官方与社区的真实落差（真正的坑在这里）

| 社区想要 | 官方态度 | 证据 |
|---|---|---|
| **摆脱 Docker** | **没接**（PR #1383「Conda only」改了 781 文件，closed **unmerged**；#1393 podman 官方未表态） | 代码默认虽是 conda，但 `generate_data_folder_from_qlib()` 仍无条件用 Docker |
| Windows/macOS 可用 | **「currently only supports Linux」** | #1064 Win11 挂载路径、#990 `/tmp/full:D:\...` too many colons、#1328 WSL2 去远端拉 `local_qlib` |
| 大内存机器上稳定 | **未答复** | #1327 / #1262 均 open，36–46GB 仍爆 |
| 自动调度可信 | **默认残缺** | #1451：bandit 的 ARR/sharpe 奖励恒为 0 |
| 容器别泄漏 | ✅ 已修 | #971 → PR #975 |
| 稳定版跟进 main | 无新 release | v0.8.0（2025-11）→ main 领先 10 个月 |

### 11.4 这对我们的策略含义

官方玩法 = 「**一台 Linux+Docker 机器上跑场景化 CLI**」；社区玩法 = 「**部署指南 + 换 LLM + 再拼一个平台**」。
**两者都没有正面回答「把 RD-Agent 接进一个已有生产平台」** —— 那正好是我们 P1 要做的
（换回测链路 + 复用沙箱 + 复用同一份 qlib 数据）。社区里最接近的 `QuantMind` 走的是
「再拼一个平台」，而不是「接进既有平台」。

**另一个值得记的判断**：社区在争取「不要 Docker」，我们比社区走得更远 ——
因为 factor-miner 的执行器容器里**已经有 qlib 0.9.7 + 同一份数据 + 内存护栏**，
所以我们的 P1 连 conda 都不需要。**这是自建执行层的红利，不是 RD-Agent 的。**

---

## 12. 实测结论：链路已跑通（含我造成的一次内存回归）

> 本节是对「因子挖掘 MCP 到底能不能跑」的实证回答。此前本节之前的所有分析里，
> 我一度把「轻工具（`factor_recent_ic` / `factor_evaluate`，纯 pandas + 沙箱，不走 qrun）能跑」
> 说成了「挖掘链路已上线」——**这是过度推断，实际这条链路从未成功产出过结果**。下面是硬证据与修复。

### 12.1 之前的真实状态：跑过，但每次都失败

| 时间 | 工具 | 结果 |
|---|---|---|
| 09-21 17:58 | `factor_oos_check` | `mining-window backtest failed: ma_5: new factor 'ma_5' failed` |
| 09-21 18:00 / 18:02 | `factor_backtest` | 提交执行器 `3a17d61cae15`/`609a83ae7f46` → 无产物 |
| 09-21 23:09 | `factor_backtest` | `handler reported failure: factor_backtest worker exception` |
| 09-21 16:40、19:42 / 09-22 16:40、19:10 | `update_data` | **4 次 3600s 超时** |

客观判据（修复前）：`/opt/mcp-suite/backtests` 里 `qlib_res.csv`/`ret.parquet`/`mlruns`/`conf.yaml` **全为 0**；
执行器容器日志里 `qrun` **提及 0 次**；athena 侧 `mining_runs`/`mining_events`/`factor_library`/`factor_exec_cache` **全 0 行**
（即 Go 挖矿大脑也没跑过一轮）。
另注：`factor-worker disk cleanup` 会定期删 `jobs/backtests`，所以失败痕迹也会被清掉。

### 12.2 两个根因（其中一个是我造成的）

1. **内存上限被砍到必挂的水平（我的回归）**：执行器 `mem_limit 2600m` + `EXECUTOR_MEM_LIMIT_MB=2300`，
   而 `README` 自己的生产实测写明 full profile（csi300 × 2008→今 × Alpha158 + LGBM）需要
   **`RLIMIT_AS > 5120MiB`（5120 即失败）、cgroup 峰值 3581MiB**。→ full 档 **100% 失败**。
   复现：`MemoryError: Unable to allocate 114. MiB for an array with shape (22, 1359114) float32`（62s 失败）。
2. **单重任务槽位会被卡死**：`update_data` 超时后日志写 `handler thread left running (not killable)`，
   槽位被永久占用 → 后续所有重任务提交被拒。
   **修正（读了 `mcp_gateway.py:367 JobQueue` 之后）**：该闸门是 **per-license-key 串行单槽**
   （同 key 已有 `queued/running` 即拒），报错 `-32029 你已有一个重任务在执行/排队中`。
   我此前写成"误报"不准确 —— 更准确的描述是：**不能把 busy 当成"没提交成功"**，
   实测出现过拿不到 `job_id` 但作业其实已在跑的情况，调用方应核对 `/metrics` 或作业台账。
   （工程上仍需一个看门狗：超时/失败的 handler 不回收，必须重启容器才清槽。）

### 12.3 修复与验证（已完成）

```yaml
# /opt/mcp-suite/docker-compose.yml（备份 /opt/backups/docker-compose.yml.bak-20260923-014550）
mem_limit: 4600m            # 2600m → 4600m：< 机器 7.4G，宿主仍受保护
memswap_limit: 4600m
EXECUTOR_MEM_LIMIT_MB: "7168"   # 2300 → 7168：> 5120 的实测门槛，VA 够用
```

设计取舍：`mem_limit(4600m) < 机器(7.4G)` 保住主机不被拖死；`RLIMIT_AS(7168) > 5120MiB` 让 qrun 的
虚拟地址空间够用（峰值 RSS 3.58GB 落在 4.6GB 容器上限内）。

| 档位 | 结果 | 证据 |
|---|---|---|
| smoke（30 票 × 2019） | ✅ **42.1s** | `metrics{IC≈0, ICIR 0.223, ann_ret_with_cost -26.3%, MDD -6.17%}` |
| **full（csi300 × 2008→今）** | ✅ **218.1s** | `ok=True`，`IC 0.01906 / RankIC 0.01565 / ICIR 0.14784 / ann_ret_with_cost +4.40% / MDD -19.69%`，net_curve 2342 点、trades 5000 笔 |

miner 侧台账已翻转：`mcp_tool_calls_total{tool="factor_backtest",status="ok"} 2`、
`mcp_queue_jobs_total{status="done"}` 首次非零；执行器实测 `mem_limit=4.6GiB / RLIMIT_AS=7168MiB`；
跑完机器 `avail 3911MB`（未冻结）。
> 注：上面那个因子是**刻意的平凡因子（2 日动量）**，用来验管道，不是在主张 alpha。
> full 档 +4.40% 年化 / MDD -19.69% 说明管道数值合理（动量叠加费用后略正），不是"惊人的结果"。

### 12.4 仍未修的问题

- **`update_data` 仍然坏**（这是数据侧独立问题，与本次修复无关）：东财 clist `502/RemoteDisconnected`、
  `mootdx` 需 `python -m mootdx bestip`、`最近交易日覆盖率过低 (155/5204)`、4 次 3600s 超时。
  → qlib 数据的"日更"这条腿目前是断的；本次验证用的是**既有面板**（`manifest version sha256:9e54bbe8…`）。
- **重任务槽位缺看门狗**：失败/超时的 handler 不回收，必须重启容器才恢复。
- **`-32029` 误报**：需在 `queued` 与 `rejected` 的判定上做互斥。

---

## 13. 社区参考：QuantMind 评估

| 项 | 事实（GitHub API / 仓库实测，2026-09-23） |
|---|---|
| 定位 | AI 原生多市场量化平台：数据底座→**因子挖掘**→模型训练→批量推理→组合回测→**QMT/通达信实盘**→监控；A股/港股/美股/期货/加密 |
| 规模 | **1528★ / 345 fork**，Python 19.3MB + TS 6.8MB（+Vue/Electron/Dockerfile），5142 个文件 |
| 活跃 | 创建 2026-04-15，**pushed 2026-09-22（每日提交）**，22 open issues，1 release（v1.0.0 桌面安装包） |
| 许可 | **AGPL-3.0** ← 传染性，见下 |
| 团队 | 贡献者 **3 人**：`qusong0627`、**`cursoragent`**、`guge199205-byte`（同队的 `QuantMind-oss` 19★，已停更 3 个月） |
| 技术栈 | 后端 FastAPI（`backend/main_oss.py` 单容器 OSS 入口）+ 前端 Electron/React/TS + docker-compose |

**它怎么集成 RD-Agent（最有价值的一条）**：把 RD-Agent **整个 vendor 进自己的仓库并改名 `alphaagent/`**
（`app/components/core/log/oai/scenarios/utils` 与上游 RD-Agent 结构一致；5142 个文件里 **947 个**是 rdagent 相关），
再由 `backend/services/engine/rd_agent/rd_agent_launcher.py` + `qlib_app/services/rd_agent_persistence.py`
**编程式拉起 + 结果持久化**，并为各市场写了 `data_pipeline/{crypto,hk,us}_data.py`。
→ 这是社区对「怎么把 RD-Agent 接进自己的平台」最成熟的答案：**vendor + launcher + persistence**。
我们的 P1「换回测链路」更轻（复用已有执行器，不搬 RD-Agent 代码），但 **launcher/persistence 的分层值得借鉴**（对应本文 P2 的 run 台账设计）。

**判断与建议**：
- **值得读**：`alphaagent/` 的改造手法、`rd_agent_launcher/persistence` 的边界划分、多市场 `data_pipeline` 结构
  （若我们要扩港美股，这比 RD-Agent 原版更贴近实战）。它的文档也成体系（50 个 A 股策略模板、因子参考、模型训练指南、QMT 接入方案）。
- **不要抄代码**：**AGPL-3.0 是传染性的** —— 把它的代码引入 LangAlpha 这类对外提供服务的平台，
  会触发向网络用户提供对应源码的义务。架构可以借鉴，代码不要复制。
- **它是产品，我们是底座**：QuantMind 自带实盘（QMT/通达信）与桌面端，属于"端到端产品"；
  LangAlpha + factor-miner + athena 是"平台 + 研究闭环"。直接采用等于用它的架构替换我们的，
  而那些 issue（桌面端下载 AccessDenied、macOS arm64、Tushare/AKShare 配置、百度云数据慢）说明它的**上手摩擦不小**。
- **一句话**：**当参考架构读，不当依赖用。**

---

## 14. 出处

**本机核验（源码级，非记忆）**
- RD-Agent `~/project/RD-Agent@v0.8.0-31-g6762f84f`：
  `app/qlib_rd_loop/factor.py:17,54-62`、`app/qlib_rd_loop/conf.py:52-71`、
  `components/workflow/rd_loop.py:31-42`、`utils/__init__.py:38-55`（`import_class`）、
  `utils/env.py:164,251,303-311,586,738,832-836,1010-1030,1159,1511`、
  `scenarios/qlib/experiment/workspace.py:13-45`、`experiment/factor_experiment.py:19-22`、
  `proposal/factor_proposal.py:61,94,111`、`developer/factor_runner.py:25`
- factor-miner-mcp：`factor_miner/{factor_eval,gen_data,factor_backtest,sandbox,factor_worker}.py` 头注 MIT attribution；
  `conf_combined_factors.yaml:3`；`README.md`（执行器内存实测、挂载要求、工具清单）
- athena：`docs/DESIGN-FACTOR-MINER.md`（全 qlib 口径设计 §2/§4/§5/§6）、
  `internal/factor/miner/*.go`（4246 行）、`internal/mcp/mining_tools.go`（3 个工具）、
  `internal/factor/miner/remote_client.go:30`
- LangAlpha：`migrations/versions/044_factor_library.py`、`src/server/services/factor_library.py:43,232`、
  `src/server/app/factors.py:223`、`docs/design/factor-board.md`
- 服务器实测：`docker inspect mcp-factor-executor`（挂载）、`/qlib_data/cn_data` 计数（6152/6142/846M）、
  `instruments/*.txt` 行数、MCPHub `/opt/mcp-hub/mcp_settings.json`（10 server，`factor-miner` 18 tools 实测）

**RD-Agent 上游生态调研（源码 tarball + GitHub API + arXiv 全文核对）**：
`~/Documents/deepseek/rdagent-research/RD-Agent-qlib-深度技术调研.md`（747 行，附原始证据留存在同目录 `raw/`）
- 仓库实测（GitHub API 2026-09-23）：14,713★ / 1,926 fork / 230 open issues / MIT / 最后推送 2026-09-15；
  最新 release = **v0.8.0（2025-11-03）**
- 官方文档：`docs/installation_and_configuration.rst`（`MODEL_COSTEER_ENV_TYPE`）、
  `docs/scens/quant_agent_fin.rst`（官方 qlib 场景口径）、`README.md`（CLI 表 / DeepSeek 配方 / UI）
- 社区：#1383「Conda only」(unmerged)、#1393 podman、#1064/#990/#1328（Windows/WSL）、
  #971→#975（容器泄漏已修）、#1327/#1262（内存，open）、#1451（bandit 奖励恒 0）、#788（DeepSeek 认证）
- 中文社区：`franxyang/RD-Agent-ETF` 的 `DEPLOYMENT_GUIDE_CN.md`、智柴网/步子哥《量化交易 RD-Agent/Qlib 实战指南》、
  CSDN《RD-Agent(Q) 实战指南：5 步搭建》、匡醍量化《微软 RD-Agent：量化人的 AI 研发搭档》
- 同构平台：`qusong0627/QuantMind`、`MrRobotop/Quant-Alpha-Factory`、`rozwer/Qlib-with-Claudex`、`mengjihao/qlib-rdagent-tqsdk`
- 论文：arXiv `2505.15155`（NeurIPS 2025）+ [MSR Asia 文章](https://www.microsoft.com/en-us/research/articles/rd-agent-quant/)

**Qlib 深度调研**：`~/Documents/deepseek/qlib-research/qlib-data-format-research.md`
（源码 `microsoft/qlib@be725493`，逐条附 URL，含 4 条纠偏 + 10 条坑 + HDF5 三路线对照）

**上游**：[microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)（MIT）、
[microsoft/qlib](https://github.com/microsoft/qlib)（MIT）
