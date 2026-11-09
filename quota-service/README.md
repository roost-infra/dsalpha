# LangAlpha quota service

自托管的套餐 / 额度 / 积分服务，替代闭源的 ginlix-platform 中 LangAlpha 用到的部分。
设计文档：`../docs/quota-service-design.md`。

## 它做什么

- 给 LangAlpha 提供 `POST /api/auth/validate`（会员信息 + 6 类 quota 门禁）
- 给长对话提供额度租约：`/api/auth/billing/leases/{acquire,release,capability}`
- 读取 LangAlpha 的 Postgres（`public.conversation_usages` / `public.computer_runs` /
  `public.computers`），在 `billing` schema 下维护套餐、钱包、流水、租约
- 管理员网页/CLI 手动分配套餐、充值（当前 M1 正在实现）

## 目录

```
quota-service/
├── quota_service/
│   ├── main.py         # 应用装配与 lifespan
│   ├── config.py       # 环境变量
│   ├── db.py           # 连接池 + schema 应用
│   ├── schema.sql      # billing schema + 初始套餐（free/pro/team）
│   ├── auth.py         # service token / 管理员 cookie
│   ├── quota.py        # 纯函数：套餐与额度判定（有单测）
│   ├── store.py        # 共用读查询
│   ├── leases.py       # 租约 acquire/release
│   └── api.py          # LangAlpha 接口
├── tests/
│   └── test_quota_math.py
└── pyproject.toml
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | ✅ | LangAlpha 的 Postgres（读写 `billing`，只读业务表） |
| `INTERNAL_SERVICE_TOKEN` | ✅ | 与 LangAlpha 共享，`X-Service-Token` |
| `ADMIN_TOKEN` | ✅ | 管理员页面/API 的登录凭据 |
| `DEFAULT_PLAN` | | 未分配套餐时的默认值，默认 `free` |
| `PER_TURN_CREDITS` | | 单轮对话默认预占上限，默认 500 |
| `LEASE_TTL_SECONDS` | | 租约 TTL，默认 300 |
| `QUOTA_AUTO_MIGRATE` | | 启动时应用 `schema.sql`，默认开启 |
| `MONTHLY_GRANT_TZ` | | 月度赠送时区，默认 `Asia/Shanghai` |
| `ALLOW_NEGATIVE_BALANCE` | | 预留的透支策略开关，默认关闭 |
| `INGEST_ENABLED` | | 启用用量入账任务，默认 `true` |
| `INGEST_INTERVAL_SECONDS` | | 入账间隔，默认 60 |
| `SANDBOX_DEFAULT_CREDITS_PER_HOUR` | | 未配置 tier 单价时的兜底，默认 166.7 |
| `HOST` / `PORT` | | 监听地址，默认 `0.0.0.0:8080` |

## 运行

```bash
cd quota-service
uv sync                 # 或：pip install -e .
uv run python -m quota_service.main
```

镜像（对应设计文档 9.1 的 `build: ./quota-service`）：

```bash
docker build -t quota-service ./quota-service
docker run --rm -p 8080:8080 \
  -e DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres \
  -e INTERNAL_SERVICE_TOKEN=... -e ADMIN_TOKEN=... quota-service
```

`schema.sql` 与 `templates/` 通过 `package-data` 打进镜像；`HEALTHCHECK` 打 `/healthz`。

启动时会自动创建 `billing` schema 并写入套餐（幂等）：

| 套餐 | 月费 | 含小时 | 月赠积分 | 沙箱档位 |
|---|---:|---:|---:|---|
| free | ¥0 | — | 0 | standard |
| basic | ¥69 | 30h | 5000 | standard |
| pro | ¥129 | 30h | 10000 | + performance |
| max | ¥299 | 30h | 15000 | + max |

积分是统一货币：token（平台 key 调用）、工具（搜索/抓取）、沙箱（按 tier 小时）都扣积分。
沙箱每小时费率取 Daytona 列表价 × 2（标准 166.7 / performance 333.3 / max 500），
自建宿主机可以后续下调。

## 用量入账（M2）

服务进程内每 60s 跑一次（`INGEST_ENABLED` 控制），直接读 LangAlpha 的库：

- `public.conversation_usages` → 扣 `token_credits` / `infrastructure_credits`
- `public.computer_runs` → 按 `resource_tier` 和运行秒数扣沙箱积分
- 每月按套餐发放 `monthly_credits`（`Asia/Shanghai`，同月只发一次）

多副本用 `pg_try_advisory_xact_lock` 保证只有一个实例入账；所有流水靠
`ledger (source, source_id)` 唯一约束幂等。`GET /metrics` 暴露入账健康度。

## CLI

```bash
export ADMIN_TOKEN=...
export QUOTA_ADMIN_URL=http://127.0.0.1:8080

quota-admin plans
quota-admin assign <user_id> basic --grant-month --note "首批用户"
quota-admin topup <user_id> 1000 --note "人工充值"
quota-admin adjust <user_id> -50 --note "对账修正"
quota-admin usage <user_id>
quota-admin tokens <user_id> --days 30
quota-admin ledger --user <user_id> --reason sandbox
quota-admin leases <user_id>
```

## Token 用量

`conversation_usages.token_usage->'by_model'` 里 LangAlpha 已按模型记好
input/output/total/cached token、调用次数和美元成本；quota-service 只读汇总，不重复计价：

- `GET /admin/api/users/{user_id}/usage?days=30` — 汇总、按模型、按天三张表
- 用户详情页 `Token 用量（近 30 天）` 区块
- `quota-admin tokens <user_id> --days N`

BYOK（用户自带 key）的轮次同样会出现在 token 统计里，但
`summary.platform_cost` 与 `token_credits` 只包含平台 key 的消耗。

## 单元测试

```bash
cd quota-service
uv run pytest -q
```

纯函数的测试不依赖数据库与网络。

## LangAlpha 侧

```bash
HOST_MODE=platform
AUTH_SERVICE_URL=http://quota-service:8080
INTERNAL_SERVICE_TOKEN=<相同值>
```

## 管理页面

浏览器打开 `http://<host>:8080/admin`，用 `ADMIN_TOKEN` 登录：

| 页面 | 内容 |
|---|---|
| `/admin` | 用户数、套餐分布、活跃租约、负余额用户 |
| `/admin/users` | 搜索/筛选用户，进入详情 |
| `/admin/users/{id}` | 改套餐、充值/调整、Token 用量（近 30 天）、查看租约与流水、强制释放租约 |
| `/admin/plans` | 套餐列表、编辑、新建 |
| `/admin/ledger` | 流水筛选 |
| `/admin/audit` | 管理员操作审计 |

JSON API（Bearer `ADMIN_TOKEN`）在 `/admin/api/*`，与页面共用同一套 service。

## 快速 smoke test

```bash
# 起一个临时 Postgres 并建最小表后
DATABASE_URL=postgresql://postgres@127.0.0.1:55432/quota_test \
INTERNAL_SERVICE_TOKEN=svc-token ADMIN_TOKEN=admin-token PORT=18080 \
uv run python -m quota_service.main

curl -s localhost:18080/healthz
curl -s -X POST localhost:18080/api/auth/validate \
  -H 'X-Service-Token: svc-token' -H 'X-User-Id: u1' \
  -H 'Content-Type: application/json' -d '{"check_quota":"chat"}'
curl -s -X POST localhost:18080/admin/api/users/u1/plan \
  -H 'Authorization: Bearer admin-token' -H 'Content-Type: application/json' \
  -d '{"plan_code":"pro","grant_month":true}'
```

## 状态

- [x] billing schema / 初始套餐（free/basic/pro/max）
- [x] validate / leases / capability
- [x] 额度计算纯函数 + 单测（10 个）
- [x] 管理员 API / 管理员网页 / CLI
- [x] 用量入账（token / 工具 / 沙箱）+ 月度赠送 + `/metrics`
- [x] 用户 token 用量报表（管理 API / 用户页 / `quota-admin tokens`）
- [x] 本地 Postgres 端到端验证（门禁、租约、管理页、入账、幂等、CLI）
- [x] Dockerfile + 打包元数据（`schema.sql`、`templates/` 进入镜像）
- [ ] 停止态磁盘计费、余额不足自动停机（M3，按需）
