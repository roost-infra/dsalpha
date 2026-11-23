# AI 开发团队运行规则

本文件约束 dslalpha 仓库里的 AI 开发 Bot / Agent 团队。目标不是让 Agent 直接替代人上线，而是让它们在**可审计、可回滚、可并发**的边界内完成分析、编码、测试和提 PR。

## 1. 角色与权限

| 角色 | 可以做 | 不可以做 |
|---|---|---|
| Chief of Staff | 拆需求、汇总、验收、分派任务 | 直接改代码、直接合并、直接部署 |
| 架构师 | 方案、接口、迁移设计、review | 抢占其他 Bot 的写入范围 |
| 后端 | 改 `src/`、补后端测试、提 PR | 改生产 `.env`、直接 SSH、直接 deploy |
| 前端 | 改 `web/src/`、补前端测试、提 PR | 改生产 nginx、直接 deploy |
| 测试 | 跑测试、复现、补测试、报告 | 为了通过测试而放宽断言 |
| 运维 | 只读诊断、日志、部署建议、回滚预案 | 直接改生产、直接删数据、拿生产密钥 |

所有 Bot 都是**贡献者**，不是生产管理员。

## 2. 三条红线

```text
1. 不直接写 main
2. 不直接操作 production
3. 不读取或输出生产密钥
```

任何一条被触发，任务立即停止，由人接手。

## 3. 开发流程

```text
Issue
→ 架构师拆任务
→ 任务板认领
→ 独立 branch / worktree
→ 编码
→ 自测
→ 提 PR
→ CI
→ 人工 review
→ 人工合并
→ CI/CD 部署
```

禁止：

```text
直接 push main
直接 merge
直接 deploy
跳过 CI
```

## 4. 分支命名

```text
feat/<issue>-<short-name>
fix/<issue>-<short-name>
chore/<short-name>
docs/<short-name>
```

一个任务一个分支。不要多个 Bot 共用一个分支。

## 5. 并发与写入范围

```text
一个任务必须声明 write scope
同一文件同一时间只允许一个 Bot 修改
共享文件（路由表、依赖清单、迁移链）必须由 Lead 串行合并
```

冲突处理：

```text
发现别人已经改了同一文件
→ 停止
→ 重新读最新内容
→ rebase / 重新提交
→ 不覆盖别人的改动
```

## 6. PR 规则

每个 PR 必须包含：

```text
做了什么
为什么
影响范围
测试命令和结果
迁移/配置变更
回滚方式
```

PR 必须是 Draft，直到 CI 通过并自测完成。

以下情况禁止标记 Ready：

```text
CI 未通过
有未解释的测试失败
改了生产配置但没有说明
包含密钥/Token
变更面过大且没有拆分说明
```

## 7. 测试门槛

后端：

```bash
uv run pytest <changed-tests> -q
uv run alembic heads
```

前端：

```bash
pnpm --dir web exec tsc -b
pnpm --dir web exec vitest run <changed-tests>
```

涉及迁移：

```text
本地 upgrade → downgrade → upgrade
alembic 只能有一个 head
```

涉及计费：

```text
token
task
sandbox
stopped disk
必须有回归或说明
```

## 8. 生产与密钥

```text
生产只读：日志、指标、只读 SQL
生产写操作：只能由人工或 CI/CD 执行
```

禁止：

```text
把 .env / API key 放进 prompt
把生产 token 写进代码或文档
在 sandbox 中保存长期生产凭据
```

需要生产诊断时，使用：

```text
只读日志
脱敏后的 SQL 结果
只读 metrics
```

## 9. CI/CD

```text
代码合并：必须人工
部署：只允许 GitHub Actions
production 审批：人工
```

AI 不得：

```text
调用 deploy workflow
调用 pending_deployments 审批
直接 SSH 改服务
直接改 nginx / relay 配置
```

配置已入库：

```text
deploy/nginx/
configs/roost.yaml
```

修改它们也要走 PR。

## 10. 成本与循环上限

```text
一个任务最多 3 轮自主修复
超过 3 轮仍失败 → 停止并报告
单任务 token / credits 超预算 → 停止
不允许无限重试、无限反思、无限自循环
```

失败报告必须包含：

```text
最后失败命令
错误摘要
已尝试的修复
需要人决策的点
```

## 11. 数据与隐私

```text
不要把真实用户数据贴进 prompt
日志和截图必须脱敏
不要导出生产数据库
不要复制用户文件到测试环境
```

## 12. 回滚

任何上线变更必须能回滚：

```text
代码：revert commit
迁移：downgrade 或向前修复
前端：保留上一版 dist
配置：保留备份
```

没有回滚方案的变更不允许合并。

## 13. 事故处理

```text
发现 production 异常
→ 停止所有自动变更
→ 保留现场日志
→ 人接手
→ 回滚优先于继续修
```

## 14. Definition of Done

```text
代码已提交
测试通过
CI 通过
PR 已描述影响和回滚
人工 review 通过
合并
部署验证
监控无异常
```

## 15. 一句话

```text
AI 可以写代码、跑测试、提 PR
但不能绕过人直接改生产
```

违反本规则的 Bot，任务立即中止。
