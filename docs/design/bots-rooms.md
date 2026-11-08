# Bots & Rooms：在 LangAlpha 上再加两层抽象

> 状态：方案（2026-11-08）。分支 `feat/bots-rooms`。
> 参考：`roostbot/docs/design/{bots,rooms,messaging,agent-collaboration,sandboxing}.md`。
> 原则：**Workspace 概念不变**；在它上面加「Bot 身份层」和「Room 群聊层」，Thread/Turn/run 管线、checkpoint、livefs、记忆、transcript 都不动。

## 1. 目标与非目标

### 目标

1. **一个会话就是一个 Bot**：`conversation_threads.bot_id` 把身份挂在会话上；同一个 Bot 的私聊、群聊、定时任务都写入它自己的会话（或它的 routine 会话），上下文连续。
2. **Bot 之间可以发消息**：点对点、可追踪（assignment），不是消息总线。
3. **群聊**：一条共享有序日志 + 一轮由成员按规则串行发言 + 每个成员只收到自己的未读增量。
4. **定时任务不再每次新开会话**：automation 归属 Bot，默认写进 Bot 的持续会话；保留 `new` 给一次性任务。
5. **不破坏现有语义**：workspace/computer/sandbox/livefs/memory/transcript/checkpoint/replay/admission 全部沿用。

### 非目标（本设计明确不做）

- 不把 Bot 做成独立进程/独立沙箱；Bot 的执行环境仍是 Workspace 绑定的那台电脑。
- 不做跨用户的团队/多租户（v2 之后再谈）。
- 不引入 Kafka/NATS 消息总线；投递 = 持久 inbox + 注入一条 user 消息。
- 不改 LangGraph 图结构、checkpoint schema、chat wire 事件类型（v1）。
- 不做 Bot 自主建群/自治讨论（`auto` responder 放 v2）。

## 2. 概念模型

```
User
 ├─ Computer                      （不变）
 │    └─ Workspace                （不变：文件夹/电脑/记忆/checkpoint 的单位）
 │         └─ Bot                 （新增：身份层）
 │              ├─ Thread  private   ← 私聊（一个会话 = 一个 Bot）
 │              ├─ Thread  routine   ← 定时任务（可选，每个 automation 一条持续会话）
 │              └─ Thread  room      ← 群聊中的成员会话（每个 (room,bot) 一条）
 └─ Room                          （新增：群聊层）
      ├─ members: Bot[] (+ User)
      ├─ log: 共享有序日志（唯一事实）
      └─ rounds: 一条用户消息 = 一轮 = 有序 slots
```

### 三层职责

| 层 | 负责 | 不负责 |
|---|---|---|
| Workspace（不变） | 文件夹、电脑、沙箱/启停/档位、文件备份、workspace 记忆、livefs | 谁在说话、人设、群聊 |
| Bot（新增） | 名字、人设、模型、skills/tools 白名单、审批级别、记忆作用域、会话归属 | 文件放哪、跑在哪台电脑 |
| Room（新增） | 共享日志、成员、responder、轮次/slots、@ 规则、公告 | 执行、上下文持久化 |

### 与现有角色的关系

- `AgentRole`（`analyst` / `chief_of_staff`）保留，成为 Bot 的属性 `bots.role`。
- 每个 Workspace 回填一个默认 Bot（role=`analyst`），每个用户回填一个 Home Bot（role=`chief_of_staff`，绑定 Home 工作区）——**存量行为不变**。
- 不指定 Bot 的旧请求：解析到 thread 的 bot；thread 没有 bot 就落到 workspace 默认 Bot。永远向后兼容。

## 3. 不变清单（实现时必须守住）

| 不动 | 说明 |
|---|---|
| `conversation_threads` / `conversation_queries` / `conversation_responses` 模型 | 只加 `bot_id` 列 |
| run 管线：admission → executor → coordinator → SSE → finalize | 完全复用 |
| LangGraph checkpoint / replay 契约 | 不动；room 上下文只注入，不进 checkpoint 的历史结构 |
| livefs / 文件备份 / workspace 记忆 / transcript | 不动 |
| `hook_outbox` 投递模式 | 复用其 at-least-once/alert 机制 |
| workspace 表 | 不动（可选加 `default_bot_id`，v1 不加，用查询解析） |
| chat wire 事件类型 | v1 不新增；Bot 消息作为普通 user 消息进入会话 |

## 4. 数据模型（迁移 112）

> 表名/列名以实际 schema 为准：会话表是 `conversation_threads`，主键 `thread_id`；运行表 `conversation_responses`。

```sql
-- 4.1 Bot（身份层）
CREATE TABLE bots (
    bot_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    workspace_id      UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name              VARCHAR(64) NOT NULL,
    role              VARCHAR(32) NOT NULL DEFAULT 'analyst'
                          CHECK (role IN ('analyst','chief_of_staff')),
    persona           TEXT NOT NULL DEFAULT '',
    avatar            JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider          VARCHAR(64),
    model             VARCHAR(128),          -- NULL = 跟随会话/线程的模型（存量默认 bot）
    skills            JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools_allow       JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools_deny        JSONB NOT NULL DEFAULT '[]'::jsonb,
    approval          VARCHAR(16) NOT NULL DEFAULT 'ask'
                          CHECK (approval IN ('ask','edits','auto','full')),
    memory_scopes     JSONB NOT NULL DEFAULT '["workspace"]'::jsonb,
    status            VARCHAR(16) NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','paused')),
    primary_thread_id UUID,
    created_by        VARCHAR(255) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, name)
);
CREATE UNIQUE INDEX ix_bots_one_home ON bots (user_id)
    WHERE role = 'chief_of_staff';

CREATE TABLE bot_versions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id     UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    field      VARCHAR(32) NOT NULL,
    value      JSONB NOT NULL,
    actor      VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4.2 会话归属（只加一列）
ALTER TABLE conversation_threads ADD COLUMN bot_id UUID REFERENCES bots(bot_id) ON DELETE SET NULL;
CREATE INDEX ix_threads_bot ON conversation_threads (bot_id);

-- 4.3 Bot 的会话映射（私聊/room/routine）
CREATE TABLE bot_threads (
    bot_id    UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES conversation_threads(thread_id) ON DELETE CASCADE,
    kind      VARCHAR(16) NOT NULL CHECK (kind IN ('private','room','routine')),
    room_id   UUID,
    seen_seq  BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bot_id, thread_id)
);
CREATE UNIQUE INDEX ix_bot_threads_room ON bot_threads (bot_id, room_id)
    WHERE room_id IS NOT NULL;

-- 4.4 房间（群聊层）
CREATE TABLE rooms (
    room_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name         VARCHAR(64) NOT NULL,
    host_bot_id  UUID REFERENCES bots(bot_id) ON DELETE SET NULL,
    responder    VARCHAR(64) NOT NULL DEFAULT 'everyone',  -- everyone | mentions | member:<botId>
    bulletin     TEXT NOT NULL DEFAULT '',
    status       VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX ix_rooms_name ON rooms (workspace_id, name);

CREATE TABLE room_members (
    room_id     UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    member_type VARCHAR(16) NOT NULL CHECK (member_type IN ('bot','user')),
    member_id   VARCHAR(255) NOT NULL,
    role        VARCHAR(16) NOT NULL DEFAULT 'member' CHECK (role IN ('host','member')),
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, member_type, member_id)
);

-- 共享有序日志（唯一事实；每个成员按 seen_seq 投影增量）
CREATE TABLE room_log (
    room_id    UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    seq        BIGSERIAL,
    round_id   UUID,
    sender_type VARCHAR(16) NOT NULL CHECK (sender_type IN ('bot','user','system')),
    sender_id  VARCHAR(255) NOT NULL,
    kind       VARCHAR(16) NOT NULL DEFAULT 'message'
                  CHECK (kind IN ('message','pass','status','system')),
    content    TEXT NOT NULL,
    metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, seq)
);

CREATE TABLE room_rounds (
    round_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id      UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    started_by   VARCHAR(255) NOT NULL,
    start_seq    BIGINT NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','finished','failed')),
    slots        JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{i, bot_id, state, run_id}]
    slot_cursor  INTEGER NOT NULL DEFAULT 0,
    lease_owner  VARCHAR(64),
    lease_until  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX ix_room_one_running_round ON room_rounds (room_id)
    WHERE status IN ('queued','running');

-- 4.5 Bot 间消息（点对点；不是房间多播）
CREATE TABLE bot_messages (
    message_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    from_type    VARCHAR(16) NOT NULL CHECK (from_type IN ('bot','user','system')),
    from_id      VARCHAR(255) NOT NULL,
    to_bot_id    UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    kind         VARCHAR(16) NOT NULL DEFAULT 'message'
                    CHECK (kind IN ('message','request','reply','report','question','notice')),
    content      TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    idem         VARCHAR(128),
    status       VARCHAR(16) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','delivered','consumed','failed')),
    thread_id    UUID REFERENCES conversation_threads(thread_id) ON DELETE SET NULL,
    in_reply_to  UUID REFERENCES bot_messages(message_id) ON DELETE SET NULL,
    root_id      UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX ix_bot_messages_idem ON bot_messages (user_id, idem) WHERE idem IS NOT NULL;
CREATE INDEX ix_bot_messages_inbox ON bot_messages (to_bot_id, status, created_at);

-- 4.6 协作状态（消息只是指针，状态在这里）
CREATE TABLE assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    from_bot_id   UUID REFERENCES bots(bot_id) ON DELETE SET NULL,
    to_bot_id     UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
    thread_id     UUID REFERENCES conversation_threads(thread_id) ON DELETE SET NULL,
    status        VARCHAR(16) NOT NULL DEFAULT 'requested'
                     CHECK (status IN ('requested','working','needs_input','done','failed','cancelled')),
    outcome       VARCHAR(32),
    evidence      JSONB NOT NULL DEFAULT '[]'::jsonb,
    depth         INTEGER NOT NULL DEFAULT 0,
    root_id       UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at     TIMESTAMPTZ
);

-- 4.7 定时任务与 Bot 绑定
ALTER TABLE automations ADD COLUMN bot_id UUID REFERENCES bots(bot_id) ON DELETE SET NULL;
CREATE INDEX ix_automations_bot ON automations (bot_id);
```

### 回填（同一迁移末尾，或独立数据迁移）

1. 每个用户：若 Home 工作区行不存在则创建（现有 `home_workspace` 逻辑），回填一个 `role='chief_of_staff'` 的 Bot，`model=NULL`。
2. 每个 Workspace：回填一个 `role='analyst'` 的 Bot（`name` 用 workspace `name`；重名时加后缀），`model=NULL`。
3. `conversation_threads.bot_id`：在 Home 工作区的线程 → Home Bot；其他 → 该 workspace 的默认 Bot。
4. `automations.bot_id`：→ 该 automation `workspace_id` 的默认 Bot。
5. `bot_threads`：为每个 Bot 的存量线程写映射（kind=`private`）。
6. **不改** `automations.thread_strategy`（行为不变）；另提供显式脚本 `scripts/automations_to_persistent.py --dry-run` 给运维确认后批量切换。

## 5. Bot 身份与生命周期

- 创建：`POST /api/v1/bots`（name/role/workspace/persona/model/skills/tools/approval）。名称锁：同 workspace 唯一 + 事务内 `INSERT ... ON CONFLICT` 处理并发。
- 模型：新建 Bot 的 `model` 必须具体；`model NULL` 仅存量回填 Bot 使用（= 跟随线程的模型，保持旧行为）。
- 修改：persona/model/skills/tools/approval 走 `bot_versions` 留痕 + `bot.updated` 事件；`workspace_id` 不可改（迁移走工作区迁移逻辑）。
- 暂停：`status='paused'` → 不接新轮次（私聊发消息返回 409、room 里跳过、automation 跳过）；进行中的 run 跑完。
- 删除：软删（`status='archived'` 或 `deleted_at`），7 天可恢复；room 成员保留占位显示"已删除"。
- 内置 Bot：每用户 Home Bot（CoS）；每个 workspace 默认 Bot。删除 workspace 前要求先删/迁移 Bot。

## 6. 会话归属（一个会话 = 一个 Bot）

- `conversation_threads.bot_id` 决定这条 thread 属于谁。
- 三种线程：
  - `private`：Bot 私聊（用户 ↔ Bot）；一个 Bot 默认一条（`bots.primary_thread_id`，首次发消息时创建）。
  - `routine`：定时任务的持续会话；`automations.thread_strategy='continue'` 时钉住的就是它；也可多条（每个 automation 一条）。
  - `room`：群聊成员会话，每个 `(room, bot)` 一条，记在 `bot_threads`。
- **请求路由**：`turn_route` 扩展为先解析 Bot（请求显式 `bot_id` → thread.bot_id → workspace 默认 Bot），再由 Bot 给出 `role` 和 `workspace_id`；解析结果与现有 `TurnRoute` 同构，下游零改动。
- **Bot 消息注入**：Bot 发给 Bot 的消息进入目标 Bot 的会话，作为一条 user 角色消息，正文第一块是发送者框（见 §7.1）。

## 7. Bot 间消息（点对点）

### 7.1 注入形态（必须照做的结论）

```
[Message from <bot name>]              ← 发送者框，进正文，模型可见
<body>
```
- 元数据（from_bot、kind、idem、assignment_id）放 `conversation_queries.metadata` / `conversation_responses.metadata`，模型不可见。
- 服务端字段（from、origin）只允许服务端写：`_client_body()` 清洗客户端输入，投递走 service token + `X-From-Bot` 头。

### 7.2 投递语义

| 目标状态 | `now`（默认，纠错/补充） | `queue`（新任务） |
|---|---|---|
| 空闲 | 启动一次 run | 启动一次 run（按 inbox 顺序合并） |
| 在跑 | **steering**（复用 `wait_or_steer`） | 写 inbox，等当前 run 结束后的下一轮 |

- `send_message` 返回 `{message_id}` = 已接受；"已执行"请看 assignment/report。
- 顺序：同一 `from→to` 保序（按 `created_at, message_id`）。
- 去重：`idem` 唯一索引；重复返回原 message_id。
- 跨重启：inbox 在 Postgres；投递 worker 用 `FOR UPDATE SKIP LOCKED` 领取，状态 CAS。

### 7.3 防环与预算（三道闸）

1. 上游检查：不能发给"正在等我结果"的 Bot（按 assignment 推断）。
2. 每 root 预算：`root_id` 维度最多 64 条请求 / 96 次执行（可配）。
3. 闭环检测：120s 内 A→B→C→A 三人环 → 房间/私聊禁发 5 分钟。
4. 单轮上限：每个 Bot 每轮最多 2 条（host 4）。

### 7.4 Assignment（协作状态）

```
requested → working → done / failed / cancelled
                 ↘ needs_input → working
```
- `send_message(kind='request')` 或 CoS 的 `delegate_to_analyst` 建 assignment。
- 完成必须有 `outcome` + `evidence`（文件路径、run_id、消息 id）。
- `needs_input` 停车等人/发起者回答，不超时重试。
- 所有 assignment 事件写 `hook_outbox` 通知（复用现有 outbox）。

## 8. 房间与轮次（群聊）

### 8.1 不变量

1. 房间日志只有一份（`room_log`），不进每个成员会话重复存。
2. 成员只收到"自己没读过、且不是自己说的"增量（`bot_threads.seen_seq`）。
3. 同一房间同一时刻只有一个 round；round 内 slots 串行。

### 8.2 轮次

```
用户消息 → room_log(seq) → 开 round
  ├─ responder 生成 slots：everyone（默认，host 先）| mentions（默认 lead）| member:<id>
  ├─ 逐个 slot：
  │   1. 装配该成员上下文（§9）
  │   2. 向它的 room-thread 注入消息；空闲跑 run，忙则 steer/排队（按 round 策略：默认等）
  │   3. 等结果：超时 240s，工作宽限 15s
  │   4. 分类：posted / [PASS] / failed / missed / needs_input
  │   5. 解析回复里的 @Name → 插新 slot（受 §8.4 限额）
  ├─ 轮内用户插话 → 入日志，加入队列（不打断当前成员）
  └─ 轮结束 → room_log 写状态行 + SSE 推送
```

### 8.3 并发的实现

- `room_rounds` 上的 **partial unique index** 保证一房一轮。
- 协调器（`services/rooms/coordinator.py`）：
  - 启动 round：`INSERT ... ON CONFLICT DO NOTHING`（输者读现有 round）。
  - 推进 slot：`UPDATE room_rounds SET slot_cursor=..., lease_owner/lease_until ... WHERE round_id=? AND slot_cursor=? AND lease_owner IS NULL OR lease_until < now()`，CAS 成功者执行。
  - 恢复：扫描器（每 worker）领取 `lease_until` 过期且 `status='running'` 的 round，从 `slot_cursor` 继续；slot 内 run 用 (round_id, slot_index) 幂等键防重复。
- **禁止**进程内存注册表（LangAlpha 多 worker 硬规则）。

### 8.4 参数（初始默认，取自 roostbot 实测）

| 项 | 值 |
|---|---|
| 单成员回复超时 | 240s（工作宽限 15s） |
| 每成员每轮发言 | 2（host 4） |
| 每轮额外 turn | 4（host 4） |
| 房间成员上限 | 12 |
| 日志保留 | 最近 60 条（首轮全给，增量最多 24 条） |
| late rounds | ≤10 |
| 公告 | 2,000 字符 |
| `[PASS]` | 不写日志、UI 不显示、不算失败 |

## 9. 上下文装配

### 9.1 Bot 私聊（每次 run）

静态 system prompt 增加 `<bot>` 块（来自 `bots` 行，按 (bot, model) 缓存）：

```
<bot>
名字 / 角色 / 人设（persona）
你的工作区：<workspace 名>；你的计算机：<computer 标签>
</bot>
```

发送者框在 user 消息里（§7.1）。`persona` 变更走版本表 + 事件，不用重启。

### 9.2 Room 成员（每次 slot，注入为 `<system-reminder>`）

复用 `inject_inline_reminders()` 通道，顺序固定：

1. 成员清单 + 谁是 host
2. 群公告（bulletin）
3. 更早上下文（本轮之前最多 8 条）
4. 本轮增量（自己没读过、非自己说的，最多 24 条）
5. 用户引用的会话/文件
6. 谁还在工作
7. 本轮发言顺序 + 自己是第几个
8. 行为指令：一次一条短消息；没有新信息回 `[PASS]`

### 9.3 关键约束

- **room 增量不进 checkpoint**：只作为本轮注入的 system-reminder；历史 replay 仍由 checkpoint 投影。
- 私聊上下文不进群：成员要让群看到自己私聊内容，必须通过工具读取（`read_own_chat`），房间记录"它查了私聊"。
- 大内容不搬运：消息是"指针"，大文件写工作区，消息里给路径 + 摘要；单条上限 64 KB。

## 10. 定时任务与 Wakeup

### 10.1 现状（已验证）

- `automations.thread_strategy`：`new`（每次新会话）/ `continue`（首次创建并钉住会话）。
- 线上：44 个 `new`、7 个 `continue`。
- 复用会话且该线程在跑时，firing 进入 `waiting` 排队（`_wait_for_thread`），不插队。

### 10.2 改造

1. `automations.bot_id` 必填（回填）；`_turn_place()` 先解析 Bot → workspace/thread。
2. Bot 归属的 automation 默认 `thread_strategy='persistent'`（落 `continue`）。
3. 会话目标（默认 **bot_primary**，可被 automation 覆盖）：
   - `bot_primary`：写进 Bot 私聊（默认；一个会话 = 一个 Bot）
   - `routine`：每个 automation 一条持续会话（`continue` 现状；日报/扫描互不污染）
   - `new`：一次性任务（保留）
4. 触发消息加框：`[Scheduled task: <automation name>]`，作为 user 消息注入；run 的 metadata 记 `automation_id`/`execution_id`。
5. 失败回退：钉住的会话被删/移走时，新建一条并重新钉住；新会话必须仍属于同一 Bot（`bot_id` 过滤），并写 `bot.thread_fallback` 事件。
6. Wakeup：保持 thread 级（已经是对的）；wake 的 turn 会自然带上 thread 的 `bot_id`。

### 10.3 存量切换

- 不自动改 `new`（避免静默改变行为）；提供 `scripts/automations_to_persistent.py --dry-run`：
  - 列出候选（按 `new` + 近 30 天有运行 + 非一次性标记）
  - 人工确认后批量 `PATCH {"thread_strategy":"persistent"}`
- UI 的「更多选项 → 持续会话 / 每轮新会话」保留。

## 11. Prompt 与工具面

### 11.1 新增 agent 工具（主 agent，按角色/权限开放）

| 工具 | 作用 |
|---|---|
| `list_bots` | 列出同 workspace 的 Bot（名字/角色/状态） |
| `send_message(bot, kind, content, reply_policy)` | 给另一个 Bot 发消息；`kind=request` 时建 assignment |
| `assign_to_bot(bot, brief)` | 建 assignment 并交办（CoS 的 `delegate_to_analyst` 泛化） |
| `report_to(assignment, outcome, evidence)` | 完成/失败上报 |
| `read_room(room, since_seq)` / `post_to_room(room, content)` | 房间读写；`@Name` 生效 |
| `create_room(name, bots)` | v2，受每日配额限制 |
| `read_own_chat` | 让群里能引用自己的私聊（记录到 room log） |

- 工具描述遵循 `src/tools/AGENTS.md`（每句话改变决策）。
- 工具白名单来自 `bots.tools_allow/deny`，在构建 agent 时过滤；审批级别映射现有 HITL（`ask` 默认，`auto/full` 仅对内部只读工具开放）。

### 11.2 模型解析

- Bot 的 `model` 非空 → 优先；空（存量 Bot）→ 线程模型。
- Bot 的模型不可用（下线/无权）→ 拒绝并提示，不静默回退（与线程模型策略一致）。

## 12. API

```
# Bots
GET    /api/v1/bots?workspace_id=
POST   /api/v1/bots
GET    /api/v1/bots/{bot_id}
PATCH  /api/v1/bots/{bot_id}
DELETE /api/v1/bots/{bot_id}            # 软删
POST   /api/v1/bots/{bot_id}/messages   # 用户 → Bot 私聊（等价现有 thread POST，bot 由路径定）

# Rooms
GET    /api/v1/rooms?workspace_id=
POST   /api/v1/rooms
GET    /api/v1/rooms/{room_id}
PATCH  /api/v1/rooms/{room_id}          # name/responder/bulletin
POST   /api/v1/rooms/{room_id}/members  # {member_type, member_id}
DELETE /api/v1/rooms/{room_id}/members/{member_type}/{member_id}
POST   /api/v1/rooms/{room_id}/messages # 用户发一句 → 开 round
GET    /api/v1/rooms/{room_id}/stream?last_seq=   # SSE：room 事件
GET    /api/v1/rooms/{room_id}/log?before_seq=

# Automations（现有接口扩展）
PATCH  /api/v1/automations/{id}         # 接受 {bot_id, thread_strategy, conversation_thread_id}
```

所有 room 事件走**独立 SSE**，不混入 chat wire（v1）。

## 13. 流式与重放

| 通道 | 来源 | 重放来源 |
|---|---|---|
| Bot 私聊 / routine / room 成员 run | 现有 `workflow:stream:{thread}:{run}`（不变） | checkpoint（不变） |
| Room 页面 | `room:stream:{room_id}`（Redis Stream，XADD，MAXLEN） | `room_log` 表（table-sourced） |

- Room 事件：`room_message`、`round_started`、`slot_started`、`slot_finished`、`round_finished`、`member_status`、`room_updated`。
- 重连：`last_seq` 从 `room_log` 回放后 tail Redis；空洞 → `resync` 到 `room_log` 投影（同 chat 的 resync 语义）。
- **不新增 chat wire 事件类型**（避免 `test_event_ledger.py` 的 replay home 债务）；如果未来要在私聊里渲染 room 卡片，必须先登记表和重放来源。

## 14. 多 worker 与失败恢复

- 协调器：PARTIAL UNIQUE + CAS + lease（§8.3）；恢复扫描器每 worker 都跑，幂等。
- 投递 worker：`bot_messages` `FOR UPDATE SKIP LOCKED` + 状态 CAS；`idem` 去重。
- 房间成员 run 的终态：现有 `RunCoordinator.finalize_run`；slot 结果由 finalize hook 写 room_log（幂等：`(round_id, slot_index)`）。
- 服务重启：running round 由扫描器接管；`conversation_responses` 的 `in_progress` 行已有恢复扫描器。
- 验收：`scripts/multiworker_gate/` 增加 room round 用例（两 worker 下 start/steer/超时/恢复）。

## 15. 计费与配额

- 每个 slot = 一次普通 run → 现有 credit gate / burst slot / 并发上限全部生效，无需新计量。
- Room round 预算：`room_rounds.metadata.budget` 记录本轮最大 slot 数（默认 12），超限不再插 slot。
- Bot 预算（v2）：按 bot 的日/月 token 上限，超限拒绝新轮次。
- 计费口径：一轮群聊 = N 个 run 的费用；账单按 run 明细可查。

## 16. 安全与权限

- Bot 属于 workspace；room 成员必须同 workspace（v1）。跨 workspace 加群 v2 显式授权。
- Bot 继承 workspace 的信任模型：同电脑工作区互信，room 不是安全边界。
- Bot 消息是不可信 user 内容：不能自动触发高风险工具；审批级别不因"来自 Bot"提升。
- `persona`/模型/工具白名单变更留痕（`bot_versions` + 事件）。
- 密钥永不进 persona / 消息正文；仅 vault 引用。

## 17. 迁移与回填

顺序（一次迁移 + 一个脚本）：

1. `112_bots_rooms.py`：DDL + 回填 Bot + `threads.bot_id` + `automations.bot_id` + `bot_threads`。
2. 回填幂等：`INSERT ... ON CONFLICT DO NOTHING`；thread 更新用 `WHERE bot_id IS NULL`。
3. 旧客户端：不传 bot → 解析 thread.bot_id → workspace 默认 Bot；无 Bot 时按旧逻辑（role from workspace）。
4. 回滚：DDL downgrade 删表/列；`automations.bot_id` 置空；不删回填 Bot（避免误删用户数据，需运维脚本）。
5. 运行 `scripts/automations_to_persistent.py --dry-run` 供人工确认（不自动执行）。

## 18. UI

| 页面 | 内容 |
|---|---|
| 工作区页（不变） | 只加一个入口：workspace 卡片上的 Bot 数（可选） |
| Bots 页（新增，Settings 下） | 列表/创建/编辑（身份、人设、模型、技能工具、审批、记忆、暂停/删除） |
| 私聊（现有 ChatAgent） | 头部显示 Bot 头像/名字；thread 由 bot 绑定 |
| Rooms 页（新增） | 群聊：成员头像、@ 补全、round 状态（谁在说/谁跳过）、公告编辑、轮次历史 |
| 自动化页（现有） | 加「所属 Bot」「会话策略（Bot 主会话/独立持续会话/每次新会话）」 |

## 19. 分阶段与工作量

| 阶段 | 内容 | 估时 |
|---|---|---|
| **P0** | 迁移 112 + 回填 + `threads.bot_id` + Bots API/页 + 私聊绑定（行为不变） | 3–4 天 |
| **P1** | 点对点消息（`send_message` + inbox + steering/queue）+ assignments + 防环 + 测试 | 5–7 天 |
| **P2** | Room：log/rounds/coordinator + 上下文注入 + @ 规则 + Room 页/SSE + 恢复扫描 | 10–15 天 |
| **P3** | 定时任务 Bot 归属与会话策略 + routines + 预算 + 跨 workspace 授权 + UI 打磨 | 5–7 天 |

## 20. 测试计划

- **单元**：发送者框构造、thread/bot 解析（含 legacy）、slots 顺序与 @ 上限、幂等（idem/round slot）、防环、`[PASS]` 语义、persona 版本。
- **集成**：迁移回填（幂等）、私聊 now/queue/steer、round 快乐路径/超时/跳过/用户插话、automation 写持续会话、fallback（thread 被删）。
- **多 worker**：room round 两 worker 竞争、lease 过期接管、投递 worker 竞争；`scripts/multiworker_gate/` 扩展。
- **流式**：room SSE 回放/空洞 resync。
- **e2e**：建 2 Bot → 私聊互发 → 建群 → 用户一句 → 两 Bot 按 slots 各回一条 → room_log 有序。

## 21. 已拍板的决定（2026-11-08）

| # | 问题 | 决定 |
|---|---|---|
| 1 | Room 成员作用域 | **同一个 workspace**；跨 workspace 留到 v2 显式授权 |
| 2 | 用户是否占 slot | **用户是主持人**，不占 slot；用户发言 = 开一轮 |
| 3 | Bot 记忆作用域 | **继承 workspace 记忆**，v1 不新增 bot 级命名空间 |
| 4 | 群聊 responder | **可配置**：`everyone`（默认，host 先）/ `mentions` / `member:<botId>` |
| 5 | 房间上限 | **12 个 Bot**（另加主持人用户） |
| 6 | 定时任务默认目标 | **Bot 私聊**（`bot_primary`）；`routine` / `new` 为 per-automation 覆盖 |

由此确定的行为默认值：

- 新建 room：`responder='everyone'`，成员上限 12 个 Bot。
- 用户在任何群/私聊发消息：用户消息入日志并开启一轮，用户不进入 slots。
- 群聊上下文的记忆作用域 = 该 room 所属 workspace 的记忆。
- 新建 automation 且归属某个 Bot：`thread_strategy='persistent'`，目标为 Bot 私聊。

## 22. 代码改动清单

```
migrations/versions/112_bots_rooms.py                 # 新增
src/server/database/bots.py                           # 新增
src/server/database/rooms.py                          # 新增
src/server/database/bot_messages.py                   # 新增
src/server/database/assignments.py                    # 新增
src/server/services/bots/{lifecycle.py,resolver.py}   # 新增
src/server/services/rooms/{coordinator.py,dispatch.py,context.py,stream.py}  # 新增
src/server/services/bot_messages/{delivery.py,inbox.py}                      # 新增
src/server/app/bots.py                                # 新增路由
src/server/app/rooms.py                               # 新增路由
src/server/app/threads/messaging.py                   # bot 解析 + 服务端 sender 字段
src/server/services/turn_runtime.py                   # turn_route 接受 bot
src/server/services/automations/{lifecycle.py,file.py} # bot_id + 会话策略
src/server/services/automation_executor.py            # bot 归属 + 默认 persistent
src/server/services/runs/finalization.py              # slot 终态 hook 写 room_log
src/ptc_agent/agent/agent.py                          # <bot> prompt 块 + 工具
src/tools/bots/*.py                                   # list_bots/send_message/... 工具
src/tools/secretary/chief_of_staff.py                 # delegate 泛化
scripts/automations_to_persistent.py                  # 存量切换（dry-run）
web/src/pages/Bots/**                                 # 新增
web/src/pages/Rooms/**                                # 新增
web/src/locales/{en-US,zh-CN}.json                    # i18n
tests/unit/server/services/rooms/**                   # 新增
tests/integration/test_rooms_round.py                 # 新增
```

## 23. 与 roostbot 的差异

| 项 | roostbot | LangAlpha 移植 |
|---|---|---|
| 租户 | workspace（团队） | user（LangAlpha workspace = 项目文件夹，不是租户） |
| Bot 执行环境 | OpenShell 回合沙箱 | 现有 computer/workspace 沙箱 |
| 凭据 | 出站注入（supervisor） | 现有 vault/env（保持现状，不在此改造） |
| 会话 | DSH 长活 session | LangAlpha thread（checkpoint 为单位） |
| 消息投递 | 控制面转发 | 现有 `wait_or_steer` + inbox |
| 群聊日志 | events 表投影 | 新 `room_log`（不混 chat wire） |
