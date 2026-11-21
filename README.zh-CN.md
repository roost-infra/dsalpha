<h1 align="center">dsalpha</h1>

<h3 align="center">面向金融市场的 AI 研究工作台。</h3>

<p align="center">
  开源 AI Agent，研究市场、形成投资假设，<br>
  并在你设定的权限范围内，用你自己的券商账户交易。
</p>

<p align="center">
  <a href="https://dsalpha.roostbots.com"><strong>试用 dsalpha ↗</strong></a> ·
  <a href="#快速开始"><strong>快速开始</strong></a> ·
  <a href="#bots-and-rooms"><strong>Bot 与群聊</strong></a> ·
  <a href="#agent-交易"><strong>Agent 交易</strong></a> ·
  <a href="#harness-设计"><strong>Harness 设计</strong></a> ·
  <a href="#全栈架构"><strong>全栈架构</strong></a> ·
  <a href="#安全"><strong>安全</strong></a>
  <br />
  <a href="README.md">English</a> · 简体中文 · <a href="README.ja-JP.md">日本語</a>
</p>

<p align="center">
  <a href="https://github.com/roost-infra/dsalpha/stargazers"><img src="https://img.shields.io/github/stars/ginlix-ai/langalpha?style=flat-square" alt="GitHub 星标数" /></a>
  <img src="https://img.shields.io/badge/license-Apache%202.0-green?style=flat-square" alt="许可证：Apache 2.0" />
  <img src="https://img.shields.io/badge/python-3.13+-blue?style=flat-square" alt="Python 3.13+" />
  <a href="https://github.com/langchain-ai/langchain"><img src="https://img.shields.io/badge/LangChain-1c3c3c?style=flat-square&logo=langchain&logoColor=white" alt="LangChain" /></a>
  <a href="https://github.com/roost-infra/dsalpha/releases"><img src="https://img.shields.io/badge/desktop-macOS%20%7C%20Windows%20%7C%20Linux-555?style=flat-square" alt="桌面应用" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/hero-cbrs-research-dashboard.webp" alt="demo-cbrs 工作区：左侧是 Agent 查询 CBRS 报价、拉取披露文件并派出两个分析师，右侧是基于这些研究搭建的 CBRS 仪表盘，当前显示 IPO 以来的股价和事件标记，以及选中事件的注释和来源" width="900" />
</p>

## 为什么选择 dsalpha

大多数 AI 金融工具只负责回答问题。我们认为投资研究是贝叶斯式的：先写下投资假设，以及什么情况能证伪它；之后每一份财报、每一份披露文件、每一次股价变动，都会提高或降低你的信心，仓位也随之调整。这个循环要持续数周乃至数月，单靠一条提示词无法承载。

编程 Agent 是在有了专为代码设计的 harness 之后才变得好用的：一个持续存在的代码库，每次 commit 都建立在上一次之上，再加上围绕模型的工具、记忆和运行时。dsalpha 把这套 harness 带到市场，从 vibe coding 走向 vibe investing。它适配任何模型，所以模型每进步一次，它也跟着变强。两条理念决定了它的设计：

- **一笔交易是一个循环，不是一次工具调用**。投资假设保存在工作区里，研究、仓位测算、下单以及之后的盯盘，每一步都会把新证据反馈回去。
- **自主需要由你划定边界**。Agent 只在你授予的权限内行动，每一笔订单都走同一条受控路径。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/loop.webp" alt="一笔交易是一个循环：一个直觉引出研究和保存在工作区里的投资假设，接着是仓位与风险、下单和盯盘，盯盘再把新证据反馈给投资假设，改变对它的信心" width="880" />
</p>

## 功能亮点

下面的示例大多出自同一个研究 Cerebras（CBRS）的工作区。可以通过[这段分享的对话](https://dsalpha.roostbots.com/app/s/z7rvgK3P9vZN)看它的实际运行过程，从第一个问题一直到发往 Slack 的首次覆盖报告。

### 🔎 用 Agent 团队做研究

提出一个问题，dsalpha 会把它拆给多个并行的分析师：阅读披露文件，拉取价格、期权和宏观数据，再用代码完成计算。运行途中随时可以追加消息，调整它们的方向。在 CBRS 这个例子里，这次运行最终产出了[一份 HTML 入门报告](https://dsalpha.roostbots.com/app/a/lep06ly8Qjfa)，讲清 Cerebras 卖什么、增长有多快、谁在付钱。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-research-subagents-primer.webp" alt="一个 CBRS 问题分派给四个子 Agent，在侧边栏中列于主 Agent 之下，旁边是入门报告中关于谁在为 Cerebras 付费的章节" width="800" />
  <br />
  <sub><b>子 Agent</b>：四个分析师在主 Agent 之下分头处理这个问题，每张卡片统计各自的工具调用和 token 用量，一条 <code>/html-report</code> 把它们的发现整理成右侧的入门报告</sub>
</p>

### 🗂️ 每个想法都放进工作区

每个投资假设、行业或投资组合各用一个工作区。文件、对话和 Agent 自己的笔记第二天都还在，每次使用都能接着上一次继续，不必从头开始。

> *“根据这个工作区目前的研究成果，给我做一个 CBRS 的交互式仪表盘：带关键事件的股价、营收增长、客户集中度，以及有多少押在 OpenAI 身上。我想能点来点去地看。”*

新开的一段对话会基于之前各段对话留在工作区里的研究和文件把它做出来：[一个可以上手操作的实时仪表盘](https://dsalpha.roostbots.com/app/a/DB8NBmVeudB1)。

<table align="center">
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-workspace-data-files.webp" alt="研究进行中的 demo-cbrs 工作区：Agent 正在加载 xlsx 和 dcf-model 技能并运行代码获取市场输入数据，旁边打开的是 overview 任务 data 文件夹里的 revenue_history.json，文件树中每个任务各占一个文件夹" /><br /><sub><b>工作区文件</b>：大批量数据落在文件里，而不是 Agent 的上下文中。价格、披露文件和模型输入都放进文件树里各个任务的 data/ 文件夹</sub></td>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-dashboard-openai-exposure.webp" alt="仪表盘对话：搭建请求，以及一条合并另一段对话事件文件的追加消息，旁边是实时 CBRS 仪表盘中关于 OpenAI 依赖程度的页面，含敞口明细和在手订单压力测试" /><br /><sub><b>运行中的应用</b>：Agent 会搭建交互式仪表盘。点击柱子、标记或表格行可以查看来源，可以拖动 OpenAI 在手订单压力测试，也可以用 @ 引用另一段对话的文件，把它们合并进来</sub></td>
  </tr>
</table>

### ⏰ 替你盯盘的 Agent

可以安排开盘前的简报，也可以在股价突破某个价位，或单日涨跌达到设定幅度时唤醒 Agent。结果都汇总在同一个动态流里；如果连接了 Slack、Discord、Telegram、飞书或 iMessage 并选作推送目标，也会推送到那里。

> *“帮我盯着 CBRS。每周一检查一遍模型假设，Q3 财报出来后更新模型，股价突破我们的乐观情景估值或跌破 $95 时告诉我。”*

Agent 在工作区里创建了四个自动化：每周一次的假设检查，Q3 财报次日早上执行一次的模型更新，以及两个价格触发，一个设在 DCF 模型的乐观情景估值，一个设在 $95，也就是会改变评级的价位。每次运行都从工作区里的模型和笔记出发，结果发到 Slack。

<table align="center">
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/automations-cbrs-schedules-price-watches.webp" alt="自动化页面，包含每周一次的 CBRS 检查、一次财报后的模型更新和两个价格触发" /><br /><sub><b>自动化</b>：所有定时任务和价格监控集中在一个页面，显示每个监控离触发还差多少，以及结果发往哪里</sub></td>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/automations-cbrs-new-price-move.webp" alt="一个新的自动化：CBRS 较前收盘价上涨 15% 时唤醒 Agent，附带指令，结果推送到 Slack 私信" /><br /><sub><b>价格触线时</b>：股价相对前收盘价或当日开盘价的涨跌幅达到设定百分比时唤醒 Agent，并显示今日涨跌幅与你设定阈值的对比</sub></td>
  </tr>
</table>

### 📑 拿到交付物，而不只是一个回答

公式联动的 Excel 模型、PDF 和 HTML 报告、幻灯片和交互式仪表盘。内置技能覆盖 DCF、可比公司分析、财报前瞻、首次覆盖、晨报和交易推介。

> *“按卖方首次覆盖报告的格式把 CBRS 写出来：评级、目标价、投资逻辑、市场已经计入了什么、情景分析、可比公司、主要风险，还有图表。用我们已有的研究和模型。”*

首次覆盖技能基于这段对话前面的研究和反向 DCF 工作簿，写出十页报告：卖出评级、目标价 $130，加上情景分析、可比公司、风险和七张图表，输出为 PDF，另附 [HTML 版本](https://dsalpha.roostbots.com/app/a/eedVW2kllALZ)。在表格面板里选中一个区域，可以把它发回给 Agent 提问。连接 Slack 后，让它把所有内容发过来，每个文件都会出现在你的私信里，直接就能打开。

<table align="center">
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-initiation-report.webp" alt="对话旁打开的十页 CBRS 首次覆盖报告，含营收和客户集中度图表" /><br /><sub><b>文件面板</b>：HTML 报告既可以看渲染效果，也可以看源码，背后引用的披露文件和新闻稿以内联方式标注</sub></td>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-dcf-comps-workbook.webp" alt="表格面板中的 CBRS 反向 DCF 工作簿，选中的单元格可以直接加入对话" /><br /><sub><b>表格</b>：一份真实的工作簿，DCF、WACC、Comps 和 Checks 各表公式联动，旁边是为可比公司部分提供数据的研究过程</sub></td>
  </tr>
</table>

<table align="center">
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-initiation-peers.webp" alt="首次覆盖请求旁边是 PDF 查看器中的 CBRS 报告，停在用可比公司估值和利润率检验乐观情景的那一页" /><br /><sub><b>PDF 查看器</b>：在对话旁翻页、缩放查看成品 PDF，图中是用可比公司估值倍数和利润率检验乐观情景的那一页</sub></td>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/slack-cbrs-deliverables-dm.webp" alt="Agent 把首次覆盖报告、工作簿、仪表盘和研究笔记发到 Slack 私信，报告已在 Slack 中打开" /><br /><sub><b>Slack</b>：整套材料分两条消息发送，先是交付物，再是研究笔记，每个文件都是消息下的一条单独回复</sub></td>
  </tr>
</table>

### 📈 和 Agent 一起看图

Agent 在任意对话中都能读取实时行情图表，并在上面绘制支撑位和阻力位、趋势线、斐波那契位和事件标记，按代码和周期分别保存。在行情中心之外，绘制结果会以图表卡片的形式出现，点开即可在对话旁打开同一张图表。

> *“画出 CBRS 上市以来的走势，标出推动股价的事件：财报、重大合作、分析师观点和解禁。”*

Agent 先弄清每个大幅波动日的驱动因素，再把它画到实时图表上：18 个事件徽标、4 个解禁标记，以及 $185 IPO 价和一致预期目标价两条线。鼠标悬停在徽标上即可查看注释。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chart-cbrs-post-ipo-event-annotations.webp" alt="CBRS 实时日线图，带有 Agent 绘制的 IPO 以来事件徽标、解禁标记和参考线" width="800" />
  <br />
  <sub><b>实时图表</b>：每条注释都标在股价有反应的那一天，对话中再用表格列出每次波动及其来源</sub>
</p>

### 🧾 每个回答背后的证据都看得到

数据来源面板会列出 Agent 在一轮中访问过的每份披露文件、每个网页、每次数据调用和每个文件，连它在自己的 Python 和 Bash 里发起的数据调用也包括在内。你可以核查它的工作，而不只是选择相信。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/chat-cbrs-sources-panel.webp" alt="数据来源面板，列出一轮背后的子 Agent 读取、SEC 文件、市场数据和数据工具调用" width="800" />
  <br />
  <sub><b>数据来源</b>：在本轮的 14 个来源和整段对话的 560 个来源之间切换，按网页搜索与抓取、SEC 文件、市场数据和数据工具分组，每条都附有当时使用的提示词或参数</sub>
</p>

<a id="bots-and-rooms"></a>

### 🤝 Bot、群聊，以及另一个账户上的 Bot

工作区以一个 Bot 的身份回答。工作区的第一轮对话会创建它的分析师，名字与工作区相同。Home 的 Bot 是 Chief of Staff，在第一次需要 Home 时创建。设置页不提供对它的添加、编辑、暂停或删除。在 Home 里创建 Bot 会被拒绝，暂停或删除 Chief of Staff 也会被拒绝。

**在一个工作区里增加 Bot。** 打开设置 → Bot（`/settings?tab=bots`）。一个工作区最多 20 个 Bot。你添加的每一个都是分析师：名字在该工作区内唯一，人设最长 20,000 个字符，模型可选。模型留空时，跟随所在对话的模型；填写的模型必须是这个账户已经能够选择的。暂停后，这个 Bot 不再作答。删除是软删除：对话记录仍可阅读，Bot 停止回答。`tools_allow` 和 `tools_deny` 收窄主 Agent 的工具。允许列表为空表示保留全部工具；出现在拒绝列表里的名字会被去掉，即使它同时也在允许列表中。技能列表、记忆作用域和审批级别（`ask`、`edits`、`auto`、`full`）会保存并显示在 Bot 上。当前版本不会据此限制一轮可以加载哪些技能，不会强制执行记忆作用域，也不会按这个审批级别自动批准操作。自动化可以指定同一工作区里的一个 Bot。如果这个 Bot 后来被删除或暂停，这次运行会改由该工作区的分析师执行。

在这个工作区的对话里说：

> 创建一个名叫 Scout 的 Bot。人设：盯着披露文件和价格变动，只报告发生了什么变化。

**同一工作区里 Bot 之间的消息。** 主 Agent 可以列出这个工作区的 Bot，并向其中一个发送一条消息。投递会写入一条持久的收件记录，再在接收方自己的对话里发起一轮，消息框上写着发送方的名字。`request` 会记成一项待办，直到接收方报告完成或失败。到那个 Bot 自己的对话里读它：设置 → Bot、侧边栏里该 Bot 的一行，或 `/rooms` 上的私聊。下一条消息，是你让其中一个 Bot 去发送的。

`list_bots` 和 `send_bot_message` 的范围是当前工作区。你另一个工作区里的 Bot，要打开那个工作区才能联系。除非把 `BOT_MESSAGING_ENABLED` 设为 `0`、`false`、`off` 或 `no`，否则互发是开启的。正文超过 64 × 1024 个字符会被拒绝。种类为 `message`、`request`、`reply`、`question` 和 `notice`。一条消息链的默认预算都可以用环境变量改：3 跳（`BOT_MAX_CHAIN_DEPTH`）、这条链 24 条消息（`BOT_MAX_ROOT_MESSAGES`）、从第一条消息起 10 分钟（`BOT_MAX_CHAIN_AGE_SECONDS` = 600），以及每个 Bot 每分钟 8 次发送（`BOT_SEND_RATE_PER_MINUTE`）。接收方的对话正忙时，消息保持排队，稍后再次投递。接收方已暂停时，这次投递失败。这些工具，以及下面的群聊工具，绑定在主 Agent 上。子 Agent 拿不到它们。

> 向 Scout 发一个 request：这份工作区里保存的营收假设，有没有被最新的披露文件改变。它汇报之后，把这项待办总结给我。

**群聊。** `/rooms` 列出你所选工作区的群聊、每个 Bot 的私聊，以及外部 Bot。侧边栏在这些群聊和 Bot 出现之后会列出它们，并带有同一个外部 Bot 入口。新建群聊需要：在工作区内唯一的名称（1–64 个字符）、最多 12 个来自该工作区的 Bot、谁来回复、可选的主持，以及可选的公告（最多 2,000 个字符）。已暂停的 Bot 不能加入。你的一条消息开启一轮，成员按顺序在同一份共享记录上作答。“所有成员回复”时，主持先说。“只有被 @ 的 Bot 回复”会让名字以 `@名字` 出现的成员发言。一条消息如果谁也没有 @ 到，这一轮会退回为所有成员回复。“只有一个 Bot 回复”只保留一名成员。没有新内容的成员回答 `[PASS]`，这条回复不会写入记录。一条回复如果 `@名字` 点到另一名成员，可以在同一轮稍后加上该成员，最多再加 4 次发言。一名成员在一轮里最多说两次，主持最多四次。成员的这一轮发出之后，群聊最多再等 5 分钟等它结束。对话在 2 分钟后仍然忙碌的，这一发言位会被跳过。归档后记录仍可阅读，但不能再发消息。一个群聊的成员是同一个工作区的 Bot，因此使用的是这个工作区的文件和电脑。

> 建一个叫 Morning desk 的群聊，成员是 Scout 和这个工作区的分析师。所有成员回复。公告：每次回答只说一夜之间发生了什么变化。

**另一个账户上的 Bot。** 没有公开目录，也没有全局昵称。在 `/rooms` 上，外部 Bot 消息（`/rooms?guest=1`）可以为你的一个 Bot 生成链接。按钮使用默认值：168 小时、一次有效。`POST /api/v1/dm/invites` 接受的 `expires_in_hours` 为 1 到 720，`max_uses` 为 1 到 20。令牌只在创建时返回一次，库里只存它的 SHA-256 哈希。过期、使用次数和撤销，都在建立第一次联系时检查。设置了 `PUBLIC_APP_URL` 或 `APP_PUBLIC_URL` 时，响应里还会带上 `{base}/dm/{token}`。这条路径只是携带令牌。Web 应用没有 `/dm` 路由，打开它会按应用的回退进入仪表盘。请你自己把链接，或 `dm_` 令牌，交给对方。

对方把它粘贴到自己某个 Bot 的对话里，并让那个 Bot 把消息送出去（`send_invite_message`）。`POST /api/v1/dm/send` 用 `from_bot_id`、`invite_token` 和 `content` 做同一件事。第一条消息会保持排队，在你于外部 Bot 消息里接受之前，你的 Bot 不会因此开始一轮，因此不会消耗你的模型额度。每一对最多等待 3 条消息。接受会投递这些暂存的消息。拒绝会丢掉这次请求。哪个账户的 Bot 作答，这一轮就记在哪个账户上。接受之后，双方都可以在 `/rooms` 的外部会话里继续输入。输入会以本方 Bot 的 id 调用 `POST /api/v1/dm/contacts/{peer_bot_id}/send`。拉黑会把两个方向都标成 blocked。接受、拒绝和拉黑的请求体都是 `{ "bot_id": "<你的 Bot>" }`。

接收方的模型会看到发送方被标成来自另一个账户的外部 Bot，正文被标为不可信内容。每个 Bot 都在自己账户的工作区里运行。双方交换的是消息正文。这里的外部 Bot，是这个部署上的另一个 dsalpha 账户。让 ChatGPT 或 Claude 把交易交给 dsalpha，仍在[路线图](#路线图)上。

发送方 Bot 的限制是每分钟 6 条、每天 50 条外部消息（`GUEST_DM_MAX_PER_MINUTE`、`GUEST_DM_MAX_PER_DAY`）。这次发送时，服务器接受 `message`、`request`、`question`、`notice` 和 `reply`。收到外部消息的 Bot 之后回复时，使用 `reply_guest_message`，以及消息框上印出的 guest message id。默认的自托管是一个本地用户，因此没有第二个账户可以邀请。这个账户内部的 Bot 和群聊可以在那里使用。`make up` 会由容器入口执行数据库迁移，其中包括 Bot、群聊和外部联系的表。你在本机自己运行的后端使用 `make migrate`。

邀请和联系人的端点列在 [docs/guest-bot-dm.md](docs/guest-bot-dm.md)。

## Agent 交易

我们致力于把 dsalpha 做成最好的 Agent 交易 harness。券商如今已经允许 AI Agent 操作真实账户交易，而接入的 Agent 都是通用型的，下单只是众多工具调用中的又一个。在 dsalpha 里，整个 harness 正是围绕下单这一个调用设计的：

- **无论模型怎么做，限制都成立**。每个连接能做什么、哪些订单要等你批准，以及“批准后的订单只执行一次”这条规则，都在主机端强制执行，落在每笔订单都必须经过的那条[受控路径](#受控订单)上。任何提示词、任何 Agent 写的脚本都无法放宽这些限制，换用哪个模型也都一样。
- **下单路径可供审阅**。一笔订单从模型发起调用到券商收到请求，途经的每一道检查都是这个仓库里的代码。把钱交给它之前，你可以先读一遍代码，也可以在自己的机器上以同样的管控运行它。

目前已支持四家券商，适用同一套管控：

| | Robinhood | Interactive Brokers | moomoo | Webull |
| --- | :---: | :---: | :---: | :---: |
| 账户、持仓、历史记录 | ✅ | ✅ | ✅ | ✅ |
| 行情与自选列表 | ✅ | ✅ | ✅ | ✅ |
| 订单预览 | ✅ | ✅ | | |
| 模拟交易 | | | ✅ | |
| 预设订单，在券商 App 内确认 | | ✅ | | ✅ |
| 实盘下单 | ✅ | ✅ | ✅ | |

Robinhood 需要通过桌面应用连接，因为 Robinhood 只接受回跳到本地应用的登录。moomoo 覆盖美国、大中华区、日本和东南亚市场。

连接券商时，由你决定它能做什么：只读、模拟交易，还是实盘下单。

<table align="center">
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/plugins-brokerages-capabilities.webp" alt="插件页面的券商标签页，显示每个券商连接能做什么" /><br /><sub><b>券商</b>：连接你的券商账户；关联之前，每张卡片都会列出 Agent 在该券商能做什么</sub></td>
    <td width="50%" align="center" valign="top"><img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/plugins-robinhood-connect-capabilities.webp" alt="连接 Robinhood 时，Agent 可做的每件事都有一个开关，从行情数据到实盘下单，其中实盘下单保持关闭" /><br /><sub><b>能力</b>：只开启你信任的功能。根据你的持仓确定数量的订单会停在审批卡片上，你同意之前，什么都不会发到券商</sub></td>
  </tr>
</table>

## 快速开始

**用你已经付费的模型**。可以用 Claude 或 ChatGPT 订阅登录，使用 Kimi、GLM、MiniMax 或 OpenCode Go 的 coding plan，接入任意 API key，自托管时还可以运行本地模型。

**在你习惯的地方使用**。可以用浏览器、适用于 macOS、Windows 和 Linux 的[桌面应用](https://github.com/roost-infra/dsalpha/releases)，在 [dsalpha](https://dsalpha.roostbots.com) 上还能用 Slack、Discord、Telegram、飞书和 iMessage。

**托管版（beta）**。在 [dsalpha](https://dsalpha.roostbots.com) 注册，可以免费开始，也可以试用我们的某个套餐。行情数据、云端沙箱、券商连接和渠道都已为你配置好。beta 期间，套餐和功能可能调整。

**自托管**。只需要 Docker：

```bash
git clone https://github.com/roost-infra/dsalpha.git && cd langalpha
make config   # wizard: model, data sources, sandbox, web search
make up       # Postgres, Redis, backend and web app
```

打开 [http://localhost:5173](http://localhost:5173)。API 监听 8000 端口，交互式文档位于 `/docs`。

**自托管有哪些不同**。Agent、工作区、自动化、技能和受控订单的运行方式完全相同，其余部分有差异：

| | 托管版 | 自托管 |
| --- | --- | --- |
| 行情数据 | 美股及期权实时报价，含盘前盘后。中国 A 股即将上线 | Yahoo Finance 或 FMP 报价，每 60 秒刷新一次，标记为延迟行情 |
| 期权与市场结构 | 期权链和快照、空头持仓、流通股和涨跌幅榜 | 不可用 |
| 价格触发 | 基于实时逐笔数据触发 | 每 30 秒针对延迟报价轮询一次 |
| 渠道 | 在 Slack、Discord、Telegram、飞书和 iMessage 中对话，并接收自动化结果 | Web 应用和桌面应用。自动化结果发送到你自己运行的 webhook（`AUTOMATION_WEBHOOK_URL`） |
| Bot 与群聊 | 具名 Bot、群聊，以及同一部署上账户之间的邀请链接 | 具名 Bot 和群聊。邀请需要该部署上的第二个账户。默认自托管只有一个本地用户 |
| 账户 | 需要登录，每个用户的数据相互独立 | 只有一个无需登录的本地用户，任何能访问它的人都以你的身份操作，包括已连接的券商。请只在本机或私有网络中运行 |
| 模型 | 套餐内含的模型、你自己的 key，或 Claude 和 ChatGPT 登录 | 你自己的 key、coding plan、本地模型，或 Claude 和 ChatGPT 登录 |
| 可用性 | 在 AWS 美国东部全天候运行，你的电脑休眠时，自动化和价格触发也会照常执行 | 只在你的机器及其 Docker 栈运行时可用 |
| 远程访问 | 随时随地通过浏览器、桌面应用和渠道使用 | Web 应用和 API 监听所有网络接口，因此你的局域网可以访问。要从外部访问，需要你自己把服务暴露出去，并放在 VPN 或带认证的代理之后 |
| 运维 | 升级、迁移、备份和沙箱容量都已替你处理 | 升级、数据库迁移和备份由你自己负责。Docker 沙箱与你的机器共享 CPU、内存和磁盘 |

<details>
<summary><b>可选 key 及其解锁的功能</b></summary>

| Key | 解锁内容 |
| --- | --- |
| `FMP_API_KEY` | 基本面、财务报表、宏观和分析师数据（[有免费额度](https://site.financialmodelingprep.com/)） |
| `DAYTONA_API_KEY` | 来自 [Daytona](https://www.daytona.io/) 的云端沙箱。没有它时，沙箱运行在本地 Docker 中 |
| `R2_*`、`S3_*` 或 `OSS_*`，配合 `storage.provider` | Cloudflare R2、AWS S3、阿里云 OSS 或 MinIO 上的对象存储。用于保存工作区文件快照、备忘录、附件、技能归档、大型对话记录和对话小组件数据，并通过签名链接提供下载。没有存储桶时，这些数据保存在 Postgres 中，图表截图功能也会关闭 |
| `TAVILY_API_KEY`、`SERPER_API_KEY`、`EXA_API_KEY`、`PARALLEL_API_KEY`、`BOCHA_API_KEY` | 网页搜索。搜索引擎由 `agent_config.yaml` 中的 `search_api` 决定（默认 `tavily`），也可以由每个用户在设置中自行选择 |
| `FIRECRAWL_API_KEY` | 增强的网页抓取和站点爬取。内置爬虫不需要 key |
| `X_BEARER_TOKEN` | X 帖子搜索和推文串查询。在插件页面把它存入密钥库 |
| `LANGSMITH_API_KEY`、`OTEL_EXPORTER_OTLP_ENDPOINT` | 追踪和指标 |

即使不配置任何数据 key，你仍然可以使用 Yahoo Finance 的价格、基本面、分析师数据和选股，SEC EDGAR 文件，以及本地 Docker 沙箱。运行 `make help` 查看全部命令，或参阅 [CONTRIBUTING.md](CONTRIBUTING.md#quick-start) 在本机直接运行后端和 Web 应用。

</details>

## Harness 设计

**送给模型哪些上下文、以什么形式送达、模型能对什么采取行动，这些定义了 harness。**

凡是已有惯例的地方，dsalpha 都沿用前沿实验室在自家 Agent 中采用的做法：能读、写、编辑和搜索的文件工具，一个 Bash shell，以 `SKILL.md` 文件形式提供的技能，以及仿照 `AGENTS.md` 风格的工作区 `agent.md`。这些形式很可能已经出现在模型的训练数据里，模型一上手就知道怎么用。

### 工作区与记忆

一个投资假设要跟踪数周、数月甚至更久，远远超出任何上下文窗口。让 Agent 在这么长的时间里始终盯住同一个目标，靠的是工作区和记忆，所以它从一开始就拥有完整的工作区和文件系统：其余一切都建立在这个基础之上。

一台**计算机**对应一个沙箱。每个**工作区**是其中的一个文件夹，有自己的对话、文件和笔记，所以开启第二个想法只需几秒钟，不用再启动一台新机器。同一台计算机上的工作区共用一个操作系统用户；需要隔离时，请使用不同的计算机。

每个文件夹里有一份由 Agent 维护的 `agent.md`（目标、发现、对话和文件的索引）、一个共享的 `data/` 目录，以及每个任务各自的文件夹。记忆、设置和历史记录保存在服务器上，不属于任何一个沙箱。通过 FUSE 挂载，它们在每台计算机上都显示为普通文件，因此能跨计算机、跨沙箱重建保留下来，Bash、代码和文件工具也都以同样的方式访问它们：

| 存储 | 内容 |
| --- | --- |
| 记忆 | 按用户和按工作区保存的长期偏好与发现。Agent 会主动管理这些内容：记下它了解到的关于你和你工作的信息，并更新或删除过时的条目 |
| 用户资料 | 你的投资组合、自选股和偏好设置，以 JSON 文件形式供 Agent 读取和更新 |
| 自动化 | 每个自动化对应一个 JSON 文件。Agent 通过写入文件来创建、编辑或暂停自动化；服务器会先校验每次保存再让它生效，被拒绝的保存会在工具结果中报告 |
| 工作流 | 已保存的工作流脚本，Agent 可以按名称运行、编辑或新增 |
| 备忘录 | 你上传的 PDF 和笔记，经过提取和索引，供 Agent 引用。对 Agent 只读 |
| 对话记录 | 以往的每段对话，均可搜索，Agent 能查到上周自己做了什么。只读 |

### 程序化工具调用

dsalpha 从 2026 年 1 月首次发布起，就围绕程序化工具调用（programmatic tool calling）构建。Agent 不是逐个通过 JSON 调用工具，而是编写导入这些工具的 Python 代码：dsalpha 把任意 [MCP](https://modelcontextprotocol.io) server 转换成附带文档的 Python 模块，代码在沙箱中运行。这样做有两个原因：

- **工具还没用上，就已经占用了上下文**。如果以 JSON 工具的形式绑定，每个 server 的 schema 会随每次调用一起发送，不管这一轮用不用得到。在 dsalpha 中，提示词里每个 server 只占一行，Agent 第一次需要某个 server 时，再从文件里读取它的完整文档。这样既节省 token，又减少干扰，新增一个 server 也只多一行。
- **金融数据是表格，不是文字**。十来只股票十年的日线数据大约有 30,000 行。模型没法把这些当作文本来处理，直接贴进去也会占满上下文窗口。在代码里，Agent 可以对数据做聚合和转换、绘制图表，再输入估值模型或回测，只有结果会回到上下文中。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/ptc.webp" alt="程序化工具调用：模型编写代码，在沙箱中把 MCP server 作为 Python 模块导入，原始数据行留在沙箱里，只有结果返回给模型" width="880" />
</p>

代码是默认路径，但不是唯一路径。任何 MCP 工具都可以改为普通的 JSON 工具调用，在插件页面按工具设置。这适合账户操作这类敏感操作，每次调用都应该单独可见；下单工具则始终以这种方式运行，走[受控路径](#受控订单)。

### 数据与工具

批量数据通过 Python 模块在代码中处理，快速查询则以**直接**方式绑定：一次报价、一份公司概况、一份披露文件或一次选股，都是单个 JSON 工具调用，并在对话中显示为卡片。无论走哪条路径，结果大到放不进上下文时，都会存成文件，原位只留一段预览；预览不够用时，Agent 会在代码里打开这个文件。

数据源涵盖三类数据：

- **市场数据**：报价，股票、指数、加密货币、外汇和大宗商品的历史价格，期权链，选股器，以及市场和板块概览。
- **基本面与宏观**：财务报表和财务比率、分析师数据、内部人交易、财报日历和经济日历、宏观数据序列以及收益率曲线。
- **披露文件与文本**：SEC 文件和财报电话会记录、X 帖子以及网页。

dsalpha 自己的数据 server 专为代码处理而设计：每个市场数据工具都返回同样的外层结构（`symbol`、`currency`、`timezone`、`count`、`data`、`source`），时间序列按从旧到新排列，失败时返回带类型的错误码，因此 Agent 代码直接按索引取用结果，不必解析文字。

数据服务商按市场逐级回退：美股数据用 dsalpha 上的实时数据源，基本面和宏观用 FMP，Yahoo Finance 作为免费兜底。网页搜索支持 Tavily、Serper、Exa、Parallel 和博查；网页抓取使用内置爬虫，可选择交给 Firecrawl 处理，每个服务商都有各自的熔断器保护。

除了数据，Agent 还能使用以下工具：

| 分组 | Agent 能做什么 |
| --- | --- |
| 代码与文件 | 运行 Python 和 shell 命令，长任务可放到后台；读取、写入、编辑和搜索文件；为它在沙箱中运行的应用分享预览链接 |
| 网页 | 搜索、抓取页面，配合 Firecrawl 还能爬取整个站点或生成站点地图 |
| 输出 | 在对话中渲染交互式小组件，在股票的实时图表上绘制标注 |
| 协调 | 派发[子 Agent 和工作流](#子-agent-与-agent-团队)，以结构化问题向你提问，开启后还能维护待办清单 |
| Bot 与群聊 | 在主 Agent 上：给本工作区的另一个 Bot 发消息、跟踪一项请求，以及创建或阅读[群聊](#bots-and-rooms) |
| 你的连接 | 通过 OAuth 或 header 认证接入的券商和远程 MCP server，以及 Agent Plugins |
| 消息 | 在 dsalpha 上，通过已连接的渠道给你发消息，可附带文件 |

**数据溯源**层在模型上下文之外，记录 Agent 接触过的每个来源：市场数据和 MCP 调用（无论是模型直接调用工具，还是 Agent 的 Python 或 Bash 在沙箱里调用），网页搜索和抓取的页面，SEC 文件，以及 Agent 读取的文件、备忘录和记忆。每条记录都包含服务商、脱敏后的参数、时间戳和结果指纹，保留不超过 64 KB 的结果本身，并关联到发起调用的那一轮和那个 Agent（主 Agent 或子 Agent）。数据来源面板按轮次列出这些记录，API 也返回同样的记录，因此每个回答都可以对照它所依据的材料来核查。

### 子 Agent 与 Agent 团队

主 Agent 会把工作交给**子 Agent**，每个子 Agent 都有自己的上下文窗口。这样做有三个原因：

- **同时做更多的事**。子 Agent 在后台运行，可以多个并行，主 Agent 则继续工作，或继续和你对话。
- **研究更广、更深**。一个问题可以拆开分派，每家公司、每个业务分部或每个数据源交给一个子 Agent，各自按需要深挖。
- **主 Agent 始终把握全局**。子 Agent 交回的是发现，而不是背后的搜索和工具调用，所以主 Agent 的上下文里保留的是投资假设和计划，不会偏离方向。

内置五个子 Agent（`research`、`general-purpose`、`data-prep`、`equity-analyst`、`report-builder`），你也可以在 `agent_config.yaml` 中定义更多。它们始终可以联系上：主 Agent 可以给运行中的子 Agent 发送新指令，也可以带着完整历史恢复一个已完成的子 Agent。每个子 Agent 的工具调用和输出都会实时显示在界面上，你也可以直接给某个子 Agent 发消息。

**工作流**让规模更进一步。遇到大型研究时，Agent 会运行一个工作流：一段简短的 JavaScript 程序，在服务器上沙箱化的 QuickJS 运行时中，用 `agent()`、`parallel()` 和 `pipeline()` 把工作分发给子 Agent。它可以按名称运行已保存的工作流，也可以当场写一个新的。驱动循环的是程序而不是对话，所以筛选一百家公司不需要一百轮对话，不过仍然要消耗一百个子 Agent 的 token。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/teams.webp" alt="主 Agent 的上下文中只有投资假设、计划和发现，它把工作交给子 Agent，以及一个分发出一百个 agent() 调用的工作流；每个都只交回发现而不是工具调用，子 Agent 之间共享工作区文件" width="880" />
</p>

### Bot 与群聊

子 Agent 是一轮之内的工作者。Bot 是挂在一段对话上的身份。它的名字、人设和角色会作为 `<bot_identity>` 写进这一轮的提示词，这段对话之后的轮次仍使用这个 Bot。来自另一个 Bot 的消息先是一条收件记录，再变成接收方私聊里的一轮。消息框写着发送方的名字，因此这段文字是那个 Bot 发来的消息。`request` 还会建立一项待办，接收方调用 `report_to` 时关闭。

群聊是单个工作区里若干 Bot 的一份有序记录。用户的一条消息开启一轮。某个 worker 认领这一轮，再按成员逐个推进。每个成员收到公告、更早的几行，以及自己上次阅读之后新到的内容，然后它的回复被追加到记录里。`[PASS]` 会被丢掉。一轮的进度保存在该轮的行上，因此另一个 worker 可以接着做。

外部消息在接收方所有者接受联系之后，走同一条投递。在那之前，记录保持排队，不会发起一轮。工具、页面和预算见 [Bot、群聊，以及另一个账户上的 Bot](#bots-and-rooms)。

### 上下文如何构建

每次模型调用都按层组装，从最稳定到最易变依次排列，因此长时间的会话也能持续命中服务商的提示词缓存。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/context.webp" alt="一次模型调用由五层组成，从最稳定到最易变依次为：工具、系统提示词、冻结的对话基线、历史记录和行情时间戳尾部，前四层之后各有一个缓存点" width="880" />
</p>

- **系统提示词**。只有一份模板，按当前所用模型的提示词档位渲染。
- **对话基线**。在一轮开始时读取一次，随后冻结：工作区、你的偏好资料、MCP server 列表、技能清单、`agent.md`、两层记忆以及备忘录索引。之后其中任何一项发生变化，Agent 会收到一行简短的记录说明改了什么，基线本身保持逐字节不变。上下文压缩之后，或累积满 20 行记录时，基线会重建。
- **运行时信息行**。每一轮开头都有一行信息，给出当前时间、市场交易时段（在它变化时）以及距上一轮过去了多久，按每家服务商期望的方式发送。
- **引导**。Agent 工作期间你发送的消息，无论发给主 Agent 还是子 Agent，都会在它下一次调用模型之前送达。
- **上下文压缩**。先裁剪旧的工具参数，原始内容保存为文件。接近模型上限时，较早的轮次会折叠成摘要，完整的对话记录另存下来，摘要会告诉 Agent 去哪里读取。

### 模型

dsalpha 并非只为前沿模型调优。所有模型都由同一套工具和中间件驱动，因此开放权重模型也能以低得多的成本取得相近的效果。可以在对话中途切换服务商；调用失败时会先重试，再回退到你配置的备用模型。

大多数服务商都支持 Chat Completions 格式，但对其中一些来说，这只是一层兼容层，会丢掉关键信息。dsalpha 为每家服务商选择最适合其模型的 API 格式，例如 OpenAI 和 Codex 使用 OpenAI [Responses API](https://platform.openai.com/docs/api-reference/responses)，Claude、Kimi、MiniMax 和 DeepSeek 使用 Anthropic [Messages API](https://docs.anthropic.com/en/api/messages)。选择依据有两点：

- **保留思考内容**。推理内容会在一轮之内和跨轮次回传给模型，并保持各服务商自己的格式：Anthropic 的签名 thinking block、OpenAI 的加密 reasoning item、GLM 的推理文本。
- **运行时上下文走正确的通道**。harness 会向模型提供大量运行时上下文。在 OpenAI 风格的 API 上，它以 `developer` 消息发送；Anthropic 和 GLM 支持对话中途的 `system` 消息，就以这种形式发送；其他服务商则放进用户消息里。

每个模型都有三项可调设置，可以在设置中按账户统一配置，也可以按模型单独配置：

- **提示词档位**。前沿模型使用精简的提示词；较小的模型使用完整的提示词，附带示例和分步操作流程。两者出自同一份模板，因此始终保持一致。
- **推理强度**。从 `none` 到 `max` 的统一档位，会写入各厂商自己的参数，模型不支持的档位则降到最接近的可用档位。在输入框中可以为单条消息单独调整。
- **压缩预设**。从激进到宽松共四档，决定长对话多早开始压缩。默认根据模型的上下文窗口自动选择。

| 接入方式 | 服务商 |
| --- | --- |
| 订阅登录 | Claude（Claude Code）、ChatGPT（Codex） |
| Coding plan | Kimi、GLM、MiniMax、OpenCode Go |
| API key | OpenAI、Anthropic、Gemini、DeepSeek、Qwen（DashScope）、Kimi（月之暗面）、GLM（智谱）、MiniMax、OpenRouter、Groq、Cerebras |
| 本地 | Ollama、LM Studio、vLLM |

Key 和 OAuth token 都使用 pgcrypto 静态加密存储。

### 技能与插件

技能遵循 [Agent Skills](https://agentskills.io/specification) 规范，插件遵循 [Agent Plugins 1.0.0](https://agent-plugins.org) 格式。内置的 MCP server 和技能以插件包的形式放在 [`plugins/`](plugins/) 中，和你在插件页面上传或通过 git URL 安装的格式完全相同。在这些标准之上，dsalpha 还增加了：

- **技能按需加载**。提示词中每个技能只占一行清单条目，完整技能在使用斜杠命令或 Agent 读取其 `SKILL.md` 时才加载。技能自带的工具（例如自动化工具）在技能加载前保持隐藏。
- **你的技能，你的命令**。把技能打包成 zip 上传，为它指定你想要的斜杠命令；也可以让 Agent 从 GitHub 安装技能到某个工作区。
- **插件只有一个扩展块**。`mcp.json` 只接受该格式自身定义的字段。dsalpha 增加的所有内容都放在 `plugin.json` 的 `extensions["ai.langalpha"]` 下，这是该格式唯一的扩展点：每个 server 的 `description` 和 `instruction`，会进入提示词；`tool_exposure_mode`，取值 `summary` 或 `detailed`，决定 Agent 预先能看到每个工具的多少信息；以及 `secrets`，列出 server 需要的每项凭据及其绑定位置。去掉这个扩展块，包仍然可以安装到任何 Agent Plugins 宿主中。详见 [`plugins/README.md`](plugins/README.md)。
- **第三方 server 隔离运行**。代码不归 dsalpha 所有的 server 通过 `uvx` 或 `npx` 以固定版本启动，从不使用应用自身的环境，因此一侧的 SDK 升级不会影响另一侧。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/plugins-builtin-packages.webp" alt="插件页面的软件包标签页，列出六个内置插件包" width="720" />
  <br />
  <sub><b>软件包</b>：六个内置的 MCP server 与技能组合包，每个包整体开启或关闭，另外还能添加最多 50 个你自己的包</sub>
</p>

内置 35 个技能：

| 包 | 技能 |
| --- | --- |
| 研究 | DCF 模型、可比公司分析、三表模型、模型更新与检查、首次覆盖、财报前瞻与分析、投资假设跟踪、交易推介、公司概况、竞争分析、板块概览、影响分析、催化剂日历、选股思路生成、晨报、盯盘、演示文稿检查、投资组合诊断、研究规范 |
| 交付物 | Excel、Word、PowerPoint、PDF、HTML 报告、交互式仪表盘、内嵌小组件、图表标注、UI 设计 |
| 服务 | 新手引导、工作流、产品帮助 |
| 另类数据 | X 研究、网页抓取 |

致谢：部分研究技能改编自 [anthropics/financial-services-plugins](https://github.com/anthropics/financial-services-plugins)。

## 全栈架构

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/architecture.webp" alt="架构：Web、桌面端和聊天渠道连接到多 worker 的 FastAPI 后端，由后端的运行生命周期驱动 Agent；Agent 在沙箱化的计算机中工作，其文件持久化到 Postgres 和对象存储，券商和远程 MCP 调用经由出口中继发出，由中继附加凭据" width="880" />
</p>

每一轮都作为后台运行执行，与发起它的 HTTP 连接相互独立。事件经由每次运行专属的 Redis stream，通过 SSE 推送，所以关掉标签页或网络中断都不会丢失任何内容：客户端重新连接后会补上进度，已完成的轮次则从 LangGraph checkpoint 回放。Postgres 是唯一可信的数据源，Redis 只负责传输，因此后端可以运行多个 worker，任何一个都能提供事件流、消费队列或接管孤立的运行。完成配置后，Agent 的运行会追踪到 LangSmith，后端也会通过 OpenTelemetry 导出 trace 和指标。

**文件不随沙箱消失**。每一轮结束后以及每次计算机停止时，所有发生变化的工作区文件夹都会生成快照。清单（manifest）在 Postgres 中按路径记录，每个路径一行。文件内容从沙箱直接写入兼容 S3 的对象存储；没有配置对象存储时，则保存在 Postgres 中。计算机关机时，文件浏览器和下载功能照常可用，重新创建的沙箱会从快照恢复。停止满一周的 Daytona 计算机还会把整块磁盘归档到冷存储，下次启动时从中恢复。

**渠道网关**是 dsalpha 的一部分。它把 Slack、Discord、Telegram、飞书和 iMessage 中的对话接入 Web 应用所用的同一个聊天 API，并把自动化结果发到你选定的渠道。

### 受控订单

订单动用的是真金白银，所以它有自己专属的路径。下单工具固定为直接的 JSON 调用：一次调用就是一笔订单，系统可以看到、展示，也可以拦下。沙箱脚本一次执行就可能下任意多笔订单，因此下单工具从不在沙箱中开放。

<p align="center">
  <img src="https://raw.githubusercontent.com/ginlix-ai/LangAlpha/main/assets/readme/diagrams/orders.webp" alt="一笔受控订单：模型的下单调用会记录下来并展示给你审批，批准后签发一个执行令牌，出口中继验证令牌、占用唯一一次发送机会，再用已存储的凭据发出订单" width="880" />
</p>

- **按连接授权**。连接券商时，由你选择它具备哪些能力组。不管模型请求什么，中继都会拒绝这些能力组之外的调用。
- **按订单审批**。实盘订单和预设订单默认都要等你批准，模拟订单则不需要。每种模式都是一个由你控制的开关。
- **只执行一次**。一次批准会签发一个短时有效的令牌，绑定到这次尝试、这个工具以及这组参数的哈希。改动任何参数、重放请求或第二次调用，都会在中继处失败。
- **券商凭据不进沙箱**。券商 OAuth token 和远程 MCP 凭据由主机端的中继附加，Agent 写的代码永远接触不到。
- **可审阅的账本**。每一次尝试、批准、拒绝和成交都会记录在订单页面上，对账程序会对照券商自己的记录确认订单的最终状态。

### 安全

- **密钥库**。API key 只需存一次，就能在任意工作区的代码中通过 `from vault import get` 使用。密钥静态加密存储，只有所有者能查看或修改。
- **泄露脱敏**。每个工具结果送达模型之前，都会扫描其中是否包含已知的密钥值，命中的部分替换为 `[REDACTED:NAME]`。下载和分享的文件也做同样处理。
- **沙箱化执行**。Agent 代码在 Daytona 或 Docker 沙箱中运行，受保护路径守卫会拒绝触及系统目录的工具调用。

## 路线图

- [x] 研究 harness：在代码中处理数据、持久化工作区、Agent 团队
- [x] dsalpha 和桌面应用
- [x] 券商连接与受控订单
- [x] 工作区内的具名 Bot、群聊，以及同一部署上账户之间需邀请的消息
- [ ] 针对加密货币和预测市场调优的 Agent
- [ ] 让你自己的 AI Agent（ChatGPT、Claude）把交易交给 dsalpha

## 参与贡献

欢迎提交 issue 和 pull request，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。仓库包含后端和 Agent 核心（[`src/`](src/)）、Web 应用（[`web/`](web/)）、桌面端外壳（[`desktop/`](desktop/)）以及内置插件（[`plugins/`](plugins/)）。商务合作请发邮件至 [contact@ginlix.ai](mailto:contact@ginlix.ai)。

<a href="https://star-history.com/#ginlix-ai/langalpha&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ginlix-ai/langalpha&type=Date&theme=dark" />
    <img alt="Star 历史" src="https://api.star-history.com/svg?repos=ginlix-ai/langalpha&type=Date" width="600" />
  </picture>
</a>

## 免责声明

dsalpha 是软件，不是投资顾问。它产出的任何内容都不构成投资建议，也不构成买卖任何证券的推荐。Agent 只在你授予的权限内行动，你需要为账户中下的每一笔订单负责。请自行做好尽职调查。

## 许可证

[Apache 2.0](LICENSE)
