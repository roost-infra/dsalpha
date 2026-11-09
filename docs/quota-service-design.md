# LangAlpha 自托管套餐与用量计费方案

> 目标：不接支付的前提下，自托管一个 `quota-service`，支持**手动分配用户套餐**、
> 按 **LLM token / 工具调用 / 沙箱运行时长** 计费，并提供余额、租约和门禁。
> 现有的 LangAlpha 代码通过 `AUTH_SERVICE_URL` 调用它，无需改动业务逻辑。
>
> 管理侧以**管理员网页**为主（配置套餐、改用户套餐、充值、查用量），CLI 作为补充。

---

## 1. 背景

LangAlpha 的套餐、额度、积分全部依赖闭源的 **ginlix-platform**：

- 配额门禁、scope 校验、积分抵扣都通过
  `POST {AUTH_SERVICE_URL}/api/auth/validate` 完成
  （`src/server/dependencies/usage_limits.py`）
- 长对话的额度预占通过
  `POST {AUTH_SERVICE_URL}/api/auth/billing/leases/{acquire,release}`
  （`src/server/services/credit_gate_port.py`）
- `HOST_MODE=oss` 或 `AUTH_SERVICE_URL` 为空时，所有门禁**直接放行**，
  没有任何额度/计费能力（`platform_gating_active()`）

自部署平台（多用户、Supabase 登录）如果没有配 `AUTH_SERVICE_URL`，
同样没有套餐和额度。

本方案实现这个被调用的服务，并补上“用量入账”和“管理员手动配套餐”。

### 非目标

- 在线支付、发票、退款（预留扩展点，见 §12）
- 多币种
- 修改 LangAlpha 的业务代码（除非选择“独立数据库 + 上报接口”，见 §13）

---

## 2. 架构

```
                    ┌─────────────────────────────┐
                    │  LangAlpha backend          │
                    │  HOST_MODE=platform         │
                    │  AUTH_SERVICE_URL ──────────┼──┐
                    └──────────────┬──────────────┘  │
                                   │ 同库读写         │ HTTP
                                   ▼                 ▼
                    ┌───────────────────────────────────────┐
                    │ PostgreSQL                            │
                    │  public.*   （LangAlpha 业务表，只读）  │
                    │  billing.*  （套餐/钱包/流水/租约）     │
                    └──────────────┬────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ quota-service               │
                    │  · validate / leases API    │
                    │  · 用量入账任务（定时）       │
                    │  · 管理员 API / CLI          │
                    └─────────────────────────────┘
```

- **部署形态**：独立容器（docker-compose 服务 `quota-service`）
- **数据库**：推荐与 LangAlpha **共用一个 Postgres 实例**，计费数据放独立
  schema `billing`，业务表只读。省掉“用量上报”的改造
- **鉴权**：LangAlpha → quota-service 使用共享 `INTERNAL_SERVICE_TOKEN`
  （`X-Service-Token` + `X-User-Id`）

---

## 3. 与 LangAlpha 的接口契约（必须严格实现）

所有请求携带：

```
X-Service-Token: <INTERNAL_SERVICE_TOKEN>
X-User-Id: <user_id>
Content-Type: application/json
```

### 3.1 校验 / 套餐信息

```
POST /api/auth/validate
```

请求：

```json
{ "check_quota": "chat", "byok": false, "surface": "web" }
```

`check_quota` 的取值（来自代码）：

| 值 | 调用方 | 语义 |
|---|---|---|
| `chat` | `enforce_credit_limit`（**strict，fail-closed**） | 对话开始前的积分门禁 |
| `computer_count` | `enforce_computer_count`（创建电脑） | 电脑总数上限 |
| `workspace` | `enforce_computer_limit`（启动电脑） | 当前可运行电脑数上限 |
| `always_on` | `assert_always_on_allowed` | always-on 名额 |
| `spec_performance` / `spec_max` / `spec_xlarge` | `assert_spec_allowed` | 高级规格名额（共享计数） |
| 空 | `/users/me` 等 | 只取套餐/会员信息 |

响应（代码实际读取的字段）：

```json
{
  "access_tier": 1,
  "plan_display_name": "Pro",
  "scopes": [
    "workspace:provider:daytona",
    "workspace:always_on",
    "workspace:spec:performance"
  ],
  "quota": {
    "allowed": true,
    "message": null,
    "limit_type": "credit_limit",
    "credit_limit": 10000,
    "used_credits": 2000,
    "remaining_credits": 8000,
    "outstanding_debt": 0,
    "retry_after": 30,
    "workspace_limit": 5,
    "active_workspaces": 2,
    "capacity_limit": null,
    "capacity_used": null
  }
}
```

约定：

- `access_tier`：`-1` 表示无权使用（前端会引导到 setup）；
  `0/1/2...` 对应 `config.yaml` 里 features 的 `min_tier`
- `scopes` 缺失 = 不做 scope 校验（fail-open）；**返回空列表表示明确无权**
- `quota.allowed=false` 时 LangAlpha 返回 429/403，并透传
  `message`、`limit_type`、`retry_after` 与 `X-RateLimit-*`
- 计数上限 `-1` = 不限
- 计数别名兼容：`capacity_used`/`active`/`active_computers`/`active_workspaces`，
  `capacity_limit`/`limit`/`computer_limit`/`workspace_limit`（代码按顺序读第一个非 null）

### 3.2 额度租约

```
GET  /api/auth/billing/leases/capability
POST /api/auth/billing/leases/acquire
POST /api/auth/billing/leases/release
```

`capability` 响应（任意 dict，200 即可）：`{"name":"quota-service","version":1,"leases":true}`

`acquire` 请求：

```json
{
  "user_id": "u-123",
  "run_ref": "run-uuid",
  "spent_credits": 12.5,
  "rate_multiplier": 1.0,
  "byok": false
}
```

响应：

```json
{
  "granted": true,
  "ceiling_credits": 800.0,
  "ttl_seconds": 300,
  "generation": 3,
  "quota": { "allowed": true, "remaining_credits": 8000 }
}
```

约定：

- `granted` 必须是 JSON boolean（字符串 `"false"` 会被判为无 verdict）
- `ceiling_credits`：本轮允许消耗的积分上限
- `generation`：单调递增，`release` 时回传用于防并发释放
- `spent_credits` 是**本轮累计已花**（acquire 同时承担续租）
- 非 200 / 不可解析：LangAlpha 视为“无结论”，按 fail-open 继续本轮

`release` 请求：`{"user_id": "...", "run_ref": "...", "generation": 3}`；
幂等，没租约时返回 404 即可。

### 3.3 会员信息

`/users/me` 通过 `validate`（不带 `check_quota`）读取
`access_tier`、`plan_display_name`，LangAlpha 侧有 5 分钟 Redis 缓存；
`?refresh_tier=true` 会强制刷新。

### 3.4 失败语义

| 调用 | 服务不可用/非 200 时 |
|---|---|
| `validate` + `check_quota=chat` | **fail-closed**：LangAlpha 返回 503，拒绝对话 |
| `validate` 其他 | fail-open：放行 |
| `acquire` / `release` | fail-open：本轮无门禁 / 释放失败留待 TTL |

因此 **chat 门禁要求 quota-service 高可用**（至少 2 副本 + 健康检查 + 快速失败）。

---

## 4. 数据模型

所有表放在 `billing` schema，`numeric(20,6)` 存积分。

```sql
CREATE SCHEMA IF NOT EXISTS billing;

-- 套餐
CREATE TABLE billing.plans (
    code            text PRIMARY KEY,
    name            text NOT NULL,
    description     text,
    access_tier     int  NOT NULL DEFAULT 0,
    scopes          text[] NOT NULL DEFAULT '{}',
    limits          jsonb  NOT NULL DEFAULT '{}'::jsonb,
    -- 沙箱单价：tier -> credits / hour；没有的 tier 回退到 cpu/mem 单价
    sandbox_pricing jsonb  NOT NULL DEFAULT '{}'::jsonb,
    monthly_credits numeric(20,6) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 用户 -> 套餐（手动分配，无支付）
CREATE TABLE billing.user_plans (
    user_id     text PRIMARY KEY,
    plan_code   text NOT NULL REFERENCES billing.plans(code),
    assigned_by text,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    note        text
);

-- 钱包余额（= ledger 求和，冗余一层便于快速读）
CREATE TABLE billing.wallets (
    user_id    text PRIMARY KEY,
    balance    numeric(20,6) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 流水（唯一约束保证入账幂等）
CREATE TABLE billing.ledger (
    id         bigserial PRIMARY KEY,
    user_id    text NOT NULL,
    delta      numeric(20,6) NOT NULL,      -- 正=充值/退款，负=消费
    reason     text NOT NULL,               -- topup|grant|adjust|token|tool|sandbox
    source     text,                        -- conversation_usage|computer_run|manual|...
    source_id  text,                        -- 幂等键
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)              -- NULL 不参与唯一约束
);
CREATE INDEX idx_ledger_user ON billing.ledger (user_id, created_at DESC);

-- 额度租约（运行时预占；只做预留，不做实际扣费）
CREATE TABLE billing.leases (
    run_ref          text PRIMARY KEY,
    user_id          text NOT NULL,
    reserved_credits numeric(20,6) NOT NULL DEFAULT 0,
    generation       int NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    expires_at       timestamptz NOT NULL,
    released_at      timestamptz
);
CREATE INDEX idx_leases_user ON billing.leases (user_id) WHERE released_at IS NULL;

-- 沙箱增量计费水位
CREATE TABLE billing.run_billing (
    run_id           uuid PRIMARY KEY,      -- computer_runs.run_id
    user_id          text NOT NULL,
    billed_until     timestamptz NOT NULL,  -- 已计费到的时间点
    credits_billed   numeric(20,6) NOT NULL DEFAULT 0
);

-- 入账游标
CREATE TABLE billing.ingest_state (
    name       text PRIMARY KEY,
    cursor     text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 管理员操作审计
CREATE TABLE billing.admin_audit (
    id         bigserial PRIMARY KEY,
    actor      text NOT NULL,               -- 管理员标识
    action     text NOT NULL,               -- assign_plan|topup|adjust|edit_plan|release_lease
    target     text,                        -- user_id / plan_code / run_ref
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

### 默认套餐（按沙箱 tier 的月费）

用户画像：人均 <1h/天，成本由**峰值并发**决定，所以按 tier 收月费，积分作为统一货币
（token / 工具 / 沙箱都扣积分），每小时费率只用于计量和超额。

| code | 月费 | 包含 | access_tier | scopes | limits | 沙箱单价（credits/h） | 月赠积分 |
|---|---:|---|---:|---|---|---|---:|
| `free` | ¥0 | — | 0 | `[]` | 1 台、0 always-on | standard 166.7 | 0 |
| `basic` | ¥69 | 30h | 1 | `[]` | 1 台、0 always-on | standard 166.7 | 5000 |
| `pro` | ¥129 | 30h | 2 | `workspace:always_on`, `workspace:spec:performance` | 3 台、1 always-on | + performance 333.3 | 10000 |
| `max` | ¥299 | 30h | 3 | 再加 `workspace:spec:max` / `workspace:spec:xlarge` | 5 台、2 always-on | + max 500 | 15000 |

- 每小时费率取 **Daytona 列表价 × 2**（standard 165.6 ≈ 166.7、performance 332.3 ≈ 333.3、
  max 461.9 向上取整 500），作为云沙箱场景的成本上限；自建宿主 + 超卖后可整体下调。
- 月赠积分 ≈ `包含小时 × 每小时费率`，token/工具与沙箱共享这一笔积分；
  超额部分直接消耗余额，余额为 0 后下一轮对话被拒。
- `price_cny` 与 `included_hours_month` 只用于展示/对账，扣费统一走 credits。

规格档位与 scope 的对应（来自
`src/server/dependencies/usage_limits.py`）：

| resource_tier | scope | 计数 quota |
|---|---|---|
| standard | 无（不门禁） | — |
| performance | `workspace:spec:performance` | `spec_performance` |
| max | `workspace:spec:max` | `spec_max` |
| xlarge | `workspace:spec:xlarge` | `spec_xlarge` |
| always-on | `workspace:always_on` | `always_on` |
| provider | `workspace:provider:<kind>` | — |

---

## 5. 积分模型

> LangAlpha 侧积分单位：`USD_TO_CREDITS_RATE` 默认 **1000 credits/USD**；
> `credit_gate_port.py` 会检查它是否等于 canonical 值，**不要修改**。

| 来源 | 数据位置 | 计算 |
|---|---|---|
| **LLM token** | `conversation_usages.token_credits` | 已由 LangAlpha 按 `platform_cost_usd × 1000` 算好；BYOK/OAuth 调用为 0 |
| **工具/搜索** | `conversation_usages.infrastructure_credits` | 已按 `INFRASTRUCTURE_PRICING` 算好（Tavily/Bocha/Serper/Exa/Parallel/Firecrawl/WebFetch…） |
| **沙箱时长** | `computer_runs` | 本服务按 `sandbox_pricing[tier] / 3600 × 秒数` 计算；`provider_kind` 只包含 metered 的（SSH 不进账本） |
| **充值/赠送/调整** | 手工 | `ledger(reason=topup/grant/adjust)` |

入账规则：

- 只处理 **final** 的 `conversation_usages` 行（`status in
  ('completed','interrupted','error','cancelled')`），且 `credit_exempt=false`
- `delta = -total_credits`，`reason` 取 `token`（token 部分）与 `tool`
  可合并为一行 `usage`，也可拆分两行（推荐拆分，便于报表）
- `is_byok=true` 的行：token 积分为 0；工具积分是否收取由套餐决定
  （默认仍收取基础设施积分）
- 幂等键：`source='conversation_usage', source_id=conversation_usage_id`
- 沙箱幂等键：`source='computer_run', source_id='<run_id>:<billed_until_epoch>'`

余额与可用额度：

```
available = wallets.balance - Σ(active leases.reserved_credits)
```

- `validate(chat)`：`allowed = available > 0`（或达到套餐月额度上限）
- `acquire`：`ceiling = min(available, per_turn_cap)`，写/更新租约
- 透支策略（按套餐配置）：
  - `allow_negative_balance=false`：`available<=0` 直接拒绝
  - 允许透支：记录负余额，`quota.outstanding_debt` 返回绝对值；
    后续对话一律拒绝直到充值

每月赠送：

- 定时任务（每月 1 日 UTC+8）为每个 `user_plans` 记一笔
  `delta=+plans.monthly_credits`，
  幂等键 `source='grant', source_id='<user_id>:<YYYY-MM>'`
- 手动分配套餐时也可选择立即赠送当月额度

---

## 6. 用量入账流水线

一个后台任务（单实例，`pg_try_advisory_lock` 防并发），每 60s 一轮：

### 6.1 对话用量

```sql
SELECT conversation_usage_id, user_id, token_credits, infrastructure_credits,
       total_credits, is_byok, credit_exempt, created_at
FROM public.conversation_usages
WHERE status IN ('completed','interrupted','error','cancelled')
  AND created_at > :last_cursor
ORDER BY created_at
LIMIT 1000;
```

对每行在**同一事务**内：

1. 插入 `ledger`（token / tool 两笔，或一笔 usage）
2. `UPDATE wallets SET balance = balance - :credits`
3. 推进 `ingest_state.cursor`

### 6.2 沙箱时长

```sql
SELECT run_id, user_id, provider_kind, resource_tier, cpu, memory_gb,
       started_at, ended_at
FROM public.computer_runs
WHERE provider_kind = ANY(:metered_kinds)
```

- 未结束的 run：`tick = now - run_billing.billed_until`
- 已结束的 run：`tick = min(ended_at, now) - run_billing.billed_until`
- `credits = tick_seconds × price(tier) / 3600`
- 在事务内插入 ledger、更新 wallet、更新 `run_billing.billed_until`
- 单价缺失时回退到 `cpu/memory_gb` 单价（配置在 plans 或全局）

### 6.3 与租约的关系

- 租约只是**预占**，不产生扣费
- 实际扣费以 `conversation_usages` / `computer_runs` 入账为准
- 因此 `available` 同时扣除“余额已扣”和“进行中的预占”，不会超支
- 租约 TTL 到期后自动失效（后台清理 `released_at is null and expires_at < now()`）

---

## 7. 关键流程

### 7.1 一次对话

```
1. LangAlpha enforce_credit_limit → validate(check_quota=chat, strict)
   → quota.allowed ? 继续 : 429
2. credit gate middleware → leases/acquire（预占本轮上限）
3. 每个模型边界 → acquire 续租（spent_credits 累计）
4. 结束 → leases/release
5. 该 turn 的 conversation_usages 写入 LangAlpha DB
6. 本服务入账任务 → 扣 token/tool 积分，更新余额
```

### 7.2 创建 / 启动电脑

```
创建：
  assert_provider_allowed   → validate → scopes 含 workspace:provider:<kind>?
  enforce_computer_count    → validate(check_quota=computer_count)
  assert_spec_allowed       → validate(check_quota=spec_<tier>)
启动：
  enforce_computer_limit    → validate(check_quota=workspace)
  assert_always_on_allowed  → validate(check_quota=always_on)
```

计数直接从 `public.computers` 读取：

```sql
-- 总数
SELECT count(*) FROM public.computers
WHERE user_id=%s AND status NOT IN ('deleted','unbound');
-- always-on
... AND is_always_on
-- 高级规格（三档共享一个名额）
... AND resource_tier IN ('performance','max','xlarge')
```

### 7.3 用户信息

`validate` 不带 `check_quota` → 返回 `access_tier` / `plan_display_name`；
LangAlpha 缓存 5 分钟。

---

## 8. 管理端（无支付）

管理侧以**网页**为主：不接支付，所有套餐/额度都由管理员手动配置。

### 8.1 管理员页面（M1 必须）

技术选型：**FastAPI + Jinja2 + HTMX + 少量 CSS**（不起 Node 构建，和 quota-service 同进程）。
登录用 `ADMIN_TOKEN`（或 `ADMIN_USERNAME`/`ADMIN_PASSWORD`）换取一个
`HttpOnly; SameSite=Lax` 的签名 cookie，8 小时过期；管理页只在内网暴露。

页面与功能：

| 页面 | 内容 | 操作 |
|---|---|---|
| **概览 `/admin`** | 用户数、套餐分布、负余额用户、入账延迟、活跃租约数 | — |
| **用户列表 `/admin/users`** | 搜索（user_id / 邮箱）、套餐、余额、本月用量、最近活跃 | 进入详情 |
| **用户详情 `/admin/users/{id}`** | 当前套餐、余额、本月 token/工具/沙箱用量、最近流水、活跃租约 | **改套餐**、**充值**、**调整余额**（必填备注）、强制释放租约 |
| **套餐管理 `/admin/plans`** | 套餐列表 | 新建 / 编辑：`access_tier`、`scopes` 多选（daytona/always_on/spec_*）、`limits`（电脑数/always-on）、`sandbox_pricing`（各 tier credits/h）、`monthly_credits` |
| **流水 `/admin/ledger`** | 按用户/时间/类型筛选 | 导出 CSV |
| **审计 `/admin/audit`** | 谁在何时改了什么 | — |

交互约定：

- 改套餐/充值/调整都必须二次确认，并写一行 `admin_audit`
- 套餐编辑保存前展示“影响面”：当前有多少用户在该套餐
- 用户标识用 Supabase `user_id`（与 `public.users.user_id` 一致）
- 分页 + 服务端筛选，避免一次拉全量用户

管理员 API（页面同源调用）：

```
POST /admin/login                         # ADMIN_TOKEN 换 cookie
GET  /admin/api/users?q=&plan=&page=
GET  /admin/api/users/{user_id}
POST /admin/api/users/{user_id}/plan      {plan_code, note, grant_month?}
POST /admin/api/users/{user_id}/credits   {delta, reason, note}
POST /admin/api/users/{user_id}/leases/{run_ref}/release
GET  /admin/api/plans
POST /admin/api/plans
PUT  /admin/api/plans/{code}
GET  /admin/api/ledger?user_id=&from=&to=&reason=
GET  /admin/api/audit
```

### 8.2 CLI（补充，便于脚本化）

```
quota-admin plans list
quota-admin plans create <code> --name ... --tier N --scopes a,b --limits k=v ...
quota-admin assign <user_id> <plan_code> [--note "..."] [--grant-month]
quota-admin topup <user_id> <credits> [--note "..."]
quota-admin adjust <user_id> <delta> --reason ...
quota-admin usage <user_id> [--days 30]
quota-admin ledger <user_id> [--limit 50]
quota-admin leases list
```

- 所有写操作要求 `ADMIN_TOKEN`
- `assigned_by` / `note` 落库审计
- CLI 与网页共用同一套 admin API

### 8.3 安全

- 管理 API 与 LangAlpha 调用的 `/api/auth/*` 分开鉴权，绝不接受 `X-Service-Token`
- `ADMIN_TOKEN` 只从环境变量读取；登录失败限速（例如每 IP 5 次/分钟）
- 写操作全部记 `admin_audit`，不可删除（只允许导出后归档）
- 页面只挂在管理端口/内网，公网不暴露

---

## 9. 部署

### 9.1 docker-compose 片段

```yaml
quota-service:
  build: ./quota-service
  restart: unless-stopped
  environment:
    DATABASE_URL: postgresql://postgres:postgres@postgres:5432/postgres
    INTERNAL_SERVICE_TOKEN: ${INTERNAL_SERVICE_TOKEN}
    ADMIN_TOKEN: ${QUOTA_ADMIN_TOKEN}
    MONTHLY_GRANT_TZ: Asia/Shanghai
  expose: ["8080"]          # 只在内网暴露，不开公网
  depends_on: [postgres]
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/healthz"]
```

### 9.2 LangAlpha 侧

```bash
HOST_MODE=platform
AUTH_SERVICE_URL=http://quota-service:8080
INTERNAL_SERVICE_TOKEN=<与 quota-service 相同>
# 多用户登录仍是 Supabase
```

### 9.3 上线步骤

1. 建 `billing` schema + 迁移 + 初始化套餐
2. 部署服务，确认 `GET /api/auth/billing/leases/capability` 返回 200
3. 给测试用户 `assign` 套餐
4. LangAlpha 配 `AUTH_SERVICE_URL` 重启，验证：
   - `/users/me` 的 `plan_display_name` 正确
   - 超限创建电脑返回 429
   - 余额为 0 时对话返回 429（503 表示服务不可达）
   - `acquire/release` 有日志、`conversation_usages` 被入账
5. 全量用户分配套餐

### 9.4 回滚 / 紧急开关

- chat 门禁是 **fail-closed**：quota-service 挂掉 → 对话 503
- 紧急恢复：临时清空 `AUTH_SERVICE_URL` 并重启 LangAlpha（所有门禁放行），
  或把 `HOST_MODE` 切回 `oss`
- 因此建议至少 2 副本，并把数据库故障与 HTTP 故障都映射为快速 5xx

---

## 10. 安全

- `X-Service-Token` 常量时间比较；必须同时提供 `X-User-Id`
- 管理接口只在内网暴露（compose `expose`，不 `ports`），或加 mTLS
- 管理员令牌独立于服务令牌，支持轮换
- 所有金额 `numeric`，禁止 float
- 日志不打印令牌；`user_id` 可打印
- 入账任务使用 advisory lock，防止多实例重复扣费
- `ledger` 唯一约束是最后一道幂等防线

---

## 11. 可观测性

- `/metrics`（Prometheus）：
  - `quota_validate_total{result,check_quota}`
  - `quota_lease_acquire_total{granted}`
  - `quota_ingest_lag_seconds{source}`
  - `quota_ingest_errors_total{source}`
  - `quota_wallet_negative_count`
  - HTTP 延迟直方图
- 日志：validate verdict（allowed/denied + reason）、acquire/release、入账条数
- 告警：
  - validate 5xx > 0（对话会被 503）
  - ingest lag > 10 分钟
  - 负余额用户数突增

---

## 12. 与支付的解耦

`plans` 只描述“权利”（tier、scopes、limits、月赠），
充值走 `ledger(reason=topup)`。未来接支付只需：

1. 支付回调 → `topup`（幂等键用订单号）
2. 订阅型 → 定时发放 `grant`
3. 不需要改 LangAlpha 的任何代码

---

## 13. 需要拍板的决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | quota-service 与 LangAlpha 是否共用 Postgres | **共用**（独立 schema），入账零改造 |
| 2 | 套餐档位与沙箱单价 | **按 tier 月费**：free / basic ¥69 / pro ¥129 / max ¥299；积分共享，sandbox_pricing 取 Daytona 2× 上限 |
| 3 | 是否允许透支 | 不允许；负余额只作为“已发生”记录，下一轮对话被拒 |
| 4 | 月度赠送还是手动充值 | 两者都支持；月度赠送由入账任务按 `Asia/Shanghai` 每月发放一次，手动充值走管理页/CLI |
| 5 | 管理界面 | 管理员网页 + CLI，共用同一套 admin API |
| 6 | 时区 | 月度赠送按 `Asia/Shanghai` |
| 7 | BYOK 用户的工具积分 | 仍收基础设施积分（token_credits 本身为 0） |

---

## 14. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| **M1** | `billing` schema/迁移、初始套餐、`validate`、`leases acquire/release/capability`、管理员页面（概览/用户/套餐/充值/审计）、admin API | ✅ 已完成 |
| **M2** | 入账任务（token/tool/sandbox）、月度赠送、`/metrics`、CLI | ✅ 已完成 |
| **M3** | 报表导出、支付适配、多管理员账号、停止态磁盘计费、余额不足自动停机 | 按需 |

### M2 实现细节（已落地）

- 入账任务每 60s 一轮，`pg_try_advisory_xact_lock` 保证多副本只跑一个
- `conversation_usages`：按 `(created_at, conversation_usage_id)` 游标增量读取，
  分别记 `token` / `tool` 两笔流水，`credit_exempt` 跳过，幂等键 `<usage_id>:token|:tool`
- `computer_runs`：按 `run_billing.billed_until` 水位计算整秒增量，
  单价取用户套餐 `sandbox_pricing[tier]`（缺省回退 `SANDBOX_DEFAULT_CREDITS_PER_HOUR`），
  幂等键 `<run_id>:<end_epoch>`；只计 `daytona/docker/e2b` 的运行区间
- 月度赠送每天检查一次，`source_id=<user_id>:<YYYY-MM>` 保证同一月只发一次
- `/metrics` 暴露入账条目数、失败数、上次成功时间

M1+M2 完成后：套餐/scope/数量/规格门禁全部生效，余额随 token、工具、沙箱使用自动下降，
管理员可以在页面或 CLI 给用户配套餐、充值和排查流水。

### 管理员页面与 LangAlpha 的关系

管理页**不放进** LangAlpha 的 Settings：

- LangAlpha 当前没有管理员角色/后台概念，塞进去要改它的鉴权与前端
- quota-service 本就是独立服务，管理页同进程部署，天然隔离
- 管理页只在内网访问，与用户端的 LangAlpha 互不影响
