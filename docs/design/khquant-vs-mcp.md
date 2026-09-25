# 看海量化（KHQuant）调研 & 与我们 MCP 栈的对比

> 调研日期 2026-09-23。全部结论来自 GitHub API + 仓库源码/README 实测（`khscience/OSkhQuant`），
> 凡引用原文都标了出处。**先说一条需要纠正的前提**（见 §1）。

---

## 1. 先纠正前提：它不是命令行，是 **PyQt5 桌面 GUI**

| 证据 | 内容 |
|---|---|
| 仓库文件 | 顶层全是 GUI：`GUI.py`(3803 行)、`GUIkhQuant.py`(4851 行)、`GUIDataViewer.py`(3861 行)、`GUIScheduler.py`(1567 行)、`backtest_result_window.py`、`khFrame.py`、`SettingsDialog.py` |
| `项目文件说明.md` 原文 | 「看海量化交易平台（CSkhQuant）是一个基于 **Python 和 PyQt5** 开发的量化交易系统」；`GUIkhQuant.py` = 「主界面和核心控制器：集成所有子模块的主窗口界面 / 策略执行和回测功能 / 交易账户管理和连接…」 |
| `requirements.txt` | `PyQt5==5.15.11`、pandas、numpy、matplotlib、mpld3、psutil、requests、holidays、schedule、openpyxl、xlrd —— **没有任何回测框架**（无 backtrader / vn.py / qlib） |
| README 运行方式 | 「💡 **推荐使用打包好的 exe 程序**…无需安装 Python 环境和依赖」「Windows 安全提示：首次运行可能出现"Windows 已保护你的电脑"」 → 官方路径是**双击 exe** |
| README 检索 | 全局搜 `命令行 / command line / CLI / headless / 无界面` → **0 命中** |

它自己的对比表里也写着「**界面形态：PyQt5 构建的桌面 GUI**」。
> 所以「把量化回测做成命令行」这个印象不成立 —— 可能来自「策略就是一个 Python 文件、放进 `strategies/` 再在界面上点开始」这个心智模型，而不是 CLI。

---

## 2. 它到底是什么（事实）

| 维度 | 事实 |
|---|---|
| 定位 | 「为 **A 股个人投资者**，提供一个在图形化、本地化、简单实用方面表现出色的量化工具」；自述目标用户「注重易用性的个人量化爱好者」 |
| 数据/交易 | **xtquant（MiniQMT）深度集成**：`from xtquant import xtdata`（行情）、`from xtquant.xttrader import XtQuantTrader`（交易）→ 强依赖 **Windows 券商客户端**；「内置 MiniQMT 接口，开箱即用」 |
| 回测引擎 | **自研**，且逻辑与 GUI 同体（核心在 `GUIkhQuant.py`），**没有可编程 API** |
| 它自述的**不适合**（原文） | ❌ 高频/超低延迟（MiniQMT Tick 是 3 秒快照）❌ 依赖久远历史细颗粒度回测（「Tick 约 1 个月、1/5 分钟约 1 年」）❌ 多市场多资产复杂联动 ❌ **非 Windows 原生运行**（「并非官方支持路径」） |
| 规模/活跃 | 1581★ / 420 fork / 20 open issues；创建 2025-01-08，**最后推送 2026-04-18（≈5 个月前）**，版本停 V2.1.4；自述「个人维护」「用爱发电」 |
| **许可** | **CC BY-NC 4.0（署名—非商业性使用）** |

---

## 3. 与我们这套 MCP 栈的对比

| 维度 | 看海 KHQuant | 我们（MCP 栈，实测） |
|---|---|---|
| **接口形态** | PyQt5 GUI（人点按钮） | **MCP 工具**：`factor-miner` 18 个工具 + 域化服务（astock/causal/global/kronos/workbench/causal-memory） |
| **谁能调用** | 只有坐在 Windows 前的人 | **agent / 脚本 / 定时任务 / WeChat 机器人 / 平台**（MCPHub 已注册 10 个 server） |
| **可组合性** | 无 API，回测逻辑耦合在 4851 行 GUI 控制器里 | 工具级复用（`factor_backtest`/`factor_evaluate`/`factor_oos_check`…），可被 athena 的 `run_factor_mining` 编排 |
| **数据** | MiniQMT（券商客户端，历史颗粒度受限） | qlib `.bin` 846MB（6152 标的、开源 investment_data、容器内） |
| **回测引擎** | 自研事件循环 | **qlib 0.9.7 + LGBM + Alpha158/360**，口径 `with_cost`，指标与 RD-Agent 对齐 |
| **执行隔离** | 与本机同进程（GUI） | `mcp-factor-executor` 独立容器：cgroup `mem_limit 4600m` + `RLIMIT_AS 7168MiB` + `timeout 1800s` |
| **并发/异步** | GUI 单线程体验 | **异步 job 队列**（`job_status` 轮询，per-license 单槽）+ 磁盘 TTL 清理 |
| **多租户/鉴权/配额** | 无 | `X-License-Key`（miner auth=on）+ MCPHub + `quota-platform`（:3200 数据面/:3300 管理面） |
| **部署形态** | **Windows 桌面 exe** | **Linux 容器**，可远程/无人值守/多会话 |
| **面向人的报告** | ✅ 可视化回测报告窗口 + 结果视图 | tearsheet JSON + LangAlpha FactorBoard（看板） |
| **实盘** | ✅ **MiniQMT 直连下单**（核心卖点） | 纸面 trader-01 + 三层风控（**没有真实券商通道**） |
| **上手门槛** | 极低（双击 exe） | 高（要懂 MCP/容器/隧道；这一步我们自己也刚踩了一路坑） |
| **许可** | **CC BY-NC 4.0：禁商用** | 自研 + MIT 上游（可商用） |

### 结论：**"我们这套 MCP 更好"——在特定目标下成立，但不能一概而论**

**MCP 确实更强的场景（有证据）**：agent 编排、服务化、多租户/鉴权/配额、无人值守、跨平台容器化、可商用、
以及**执行隔离**（它的回测与 GUI 同进程；我们的 qrun 有 cgroup+RLIMIT 护栏 —— 这一点在生产里是生死差别）。

**它明显更强/我们缺的的**：
1. **实盘通道**（MiniQMT 直连下单）—— 我们至今只有纸面盘；
2. **面向人的交互式报告**（可视化窗口）—— 我们的 tearsheet 是给机器看的 JSON；
3. **上手门槛**（exe 双击 vs 我们的协议/隧道/容器）；
4. `无数据烦恼`：它把"数据源"这件事在券商接口层解决了。

### 但必须承认 MCP 的代价（否则不客观）

这一路我们自己踩的坑，**几乎全是"服务化"带来的摩擦**：SSE 信封解包、`job_status` 成功终态是 `done` 不是 `ok`、
`X-License-Key`、SSH 隧道 keepalive 静默死、`docker cp` 临时部署、per-license 单槽卡死、miner 被自己 cgroup OOM。
**一个 CLI 一条命令就完事**。所以更准确的表述是：

> **对外/对 agent：MCP 明显更好；对内/对自己调试与 CI：CLI 更顺。**

### 建议：**同源双出口（MCP 服务 + CLI 门面）**，而不是二选一

- 我们**已经有 CLI 入口**却没用起来：`python -m factor_miner.factor_backtest --new <name> <factor.py> --sota ... --profile smoke`
  （`factor_backtest.py` 的 `main()` + argparse 就是它）。
- 缺的是把它当**门面**：一条命令 → 一次回测 → 一份可读报告（HTML/图片）。这正是看海最值得学的地方
  （**低门槛的人机入口**），也是 LangAlpha 看板之外可以补的一环。
- **不要**照抄它的代码：CC BY-NC 禁止商用（比 QuantMind 的 AGPL 更严）。它的 GUI 结构（4851 行控制器）也不值得搬。

---

## 4. 一句话总结

看海是**给 Windows 个人的 GUI 量化工作站**（MiniQMT 生态、禁商用、半停更），我们是**给 agent 的量化服务底座**。
目标不同，谈不上谁替代谁。它有三样东西值得我们要：**实盘通道的思路、人看的报告、极低的上手门槛**；
而这三样里，前两样可以直接用我们自己的栈补上（CLI 门面 + 报告渲染），第三样只需把 CLI 包一层。

---

## 5. 出处

- 仓库：`github.com/khscience/OSkhQuant`（GitHub API 2026-09-23 抓取：1581★/420 fork/20 issues/创建 2025-01-08/最后推送 2026-04-18/default_branch=main/license=NOASSERTION）
- 源码实测：`requirements.txt`（PyQt5==5.15.11 等）、`LICENSE`（CC BY-NC 4.0 全文）、`项目文件说明.md`、
  `khFrame.py`（`from xtquant import xtdata`）、`khTrade.py`（`from xtquant.xttrader import XtQuantTrader`）
- `README.md`（138,741 字节）§1.3 对比表 / §1.5 适合 / §1.6 不适合 / §3.4 启动顺序（客户端与接口关系）
- 教程站：`https://khsci.com/khQuant/tutorial/`
