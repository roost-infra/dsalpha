# 从金融 Agent 到云端 Bot 助理：页面插件化设计方案

- 状态：Draft / 待评审
- 范围：产品定位、信息架构、内置页面插件、页面布局、迁移与验收
- 非范围：第三方插件、远程代码加载、支付/计费改造、行情数据供应商替换

## 1. 背景与目标

当前产品在官网、默认导航和 Dashboard 上都以“金融研究 Agent / A 股研究团队”呈现。这个定位带来两个问题：

1. **合规风险**：面向公众宣传金融 Agent、荐股、投资建议，容易被认定为需要持牌的业务。
2. **产品边界过窄**：把通用助理能力绑在金融场景上，非金融用户无法理解产品价值。

目标是把产品重新组织为：

> **在线云端 Bot 个人助理 + 可启用的内置能力插件**

金融行情、研究面板、交易订单等能力保留，但作为**内置插件**由用户主动启用，而不是核心产品的默认入口和宣传点。

### 1.1 成功标准

- 新用户登录后不再被要求填写投资偏好。
- 新用户默认只看到通用助理能力，不看到行情/组合/订单。
- 行情中心、研究 Dashboard 等以“内置插件”形式出现在插件页，用户可启用/禁用。
- 官网视觉不大改，内容从“金融 Agent”转为“案例展示”。
- 全程不引入第三方页面代码；插件代码随 App 发布。

## 2. 当前页面盘点

### 2.1 路由与页面

| 路由 | 当前内容 | 归属 | 处理方式 |
|---|---|---|---|
| `/` | 静态官网 Landing，金融研究平台视觉 | 官网 | 视觉保留，内容改案例页 |
| `/login`、`/auth/confirm`、`/reset-password` | 邮箱登录、确认、重置 | 核心 | 保留 |
| `/setup/*` | 模型 / API Key 配置 | 核心 | 保留 |
| `/dashboard` | 行情、组合、自选、新闻、财报日历、图表 | 核心首页 | 重写为通用助理工作台 |
| `/chat`、`/chat/t/:threadId` | Bot 对话、群聊、工作区 | 核心 | 保留，默认内容去金融化 |
| `/rooms` | Bot 群聊 / 私聊 / Bot 协作 | 核心 | 保留 |
| `/market` | 行情中心 | 金融插件 | 抽成 `market-center` 内置插件 |
| `/news/:id` | 新闻详情 | 金融插件 | 并入 `market-center` 插件 |
| `/orders` | 券商订单 | 金融插件 | 移入 `orders` 内置插件或暂不开放 |
| `/automations` | 定时任务 | 核心 | 保留，默认模板通用化 |
| `/plugins` | 当前是 MCP / 技能 / Agent 安装页 | 核心 | 改造为「内置插件 + 能力连接器」 |
| `/settings` | 账户、投资画像、套餐、模型、外观、聊天、集成等 | 核心 | 清理投资画像/交易，插件设置下沉 |
| `/welcome` | 投资偏好问卷 | 金融插件 | 已停止自动弹出；归研究插件 |
| `/legal` | 法律与第三方 attribution | 核心 | 保留并补插件条款 |
| `/s/:token`、`/a/:token` | 分享的对话 / Artifact | 核心 | 保留 |

### 2.2 当前导航

```text
Dashboard
Chat
Market
Automations
Orders（有券商订单时出现）
Plugins
Settings（移动端 / 账户菜单）
```

问题：

- `Market`、`Orders` 是核心一级入口，产品看起来就是交易/行情工具。
- 页面路由、chunk 预加载、侧栏导航都写死在 `Main.tsx` / `navItems.ts`，没有“可启用页面”的概念。
- Dashboard 的默认 preset 全部围绕行情/组合/财报。
- Settings 仍暴露投资画像；`/welcome` 已停止自动打开，但页面仍在。
- Plugins 页面当前只管理 MCP servers / skills / subagents，不管理页面。

## 3. 产品原则

1. **核心是助理，金融是插件**
   - 核心导航、默认 Dashboard、默认聊天提示词不出现金融建议类文案。
2. **只做内置插件**
   - 页面插件代码随 App 发布，不加载第三方远程代码。
   - 「安装」在产品语义上是「启用」，不是下载未审核代码。
3. **默认关闭，用户主动启用**
   - 行情、研究、订单等插件默认不启用。
   - 新用户看不到金融相关入口。
4. **能力可组合**
   - 同一个内置插件可以贡献：页面、Dashboard widget、Bot 模板、设置项。
5. **保留旧链接**
   - `/market`、`/orders` 等旧 URL 在插件启用时重定向到新页面；未启用时落到插件详情页。

## 4. 目标信息架构

### 4.1 桌面侧栏

```text
┌──────────────────────────────────┐
│ Logo / Workspace selector        │
│                                  │
│ 核心                              │
│  💬 Chat                         │
│  🏠 Dashboard                    │
│  ⏰ Automations                  │
│  🧩 Plugins                      │
│                                  │
│ 已启用插件（动态）                 │
│  📈 市场中心                      │
│  📊 研究面板                      │
│                                  │
│ 最近会话                          │
│  workspace tree / recent threads │
│                                  │
│ 账户 / 设置                       │
└──────────────────────────────────┘
```

核心导航固定为 4 项；插件入口只在启用后出现。

### 4.2 手机底栏

```text
💬 Chat    🏠 Dashboard    ⏰ Automations    🧩 Plugins    ☰ More
```

- 插件页面从 `More` 或 `Plugins` 打开，不固定占底栏。
- 设置从 `More` 进入。

### 4.3 URL 规划

| 页面 | 新 URL | 兼容 |
|---|---|---|
| 市场中心 | `/p/market` | `/market` 重定向 |
| 研究 Dashboard | `/p/research-dashboard` | `/dashboard` 仍是核心工作台 |
| 订单 | `/p/orders` | `/orders` 重定向或提示未启用 |
| 新闻详情 | `/p/market/news/:id` | `/news/:id` 兼容 |
| 核心页面 | `/chat`、`/dashboard`、`/automations`、`/plugins`、`/settings` | 不变 |

统一插件宿主路由：`/p/:pluginId/*`。

## 5. 内置插件架构

### 5.1 插件注册表

前端建立静态注册表，构建时打包，运行时只决定是否挂载。

```ts
// web/src/plugins/builtin/types.ts

export interface BuiltinPlugin {
  id: string;
  name: string;
  description: string;
  icon: string;
  version: string;
  defaultEnabled: boolean;
  pages: PageContribution[];
  dashboardWidgets?: DashboardWidgetContribution[];
  botTemplates?: BotTemplateContribution[];
  settings?: PluginSettingsContribution[];
}

export interface PageContribution {
  id: string;
  path: string;       // /p/market
  labelKey: string;
  component: () => Promise<{ default: React.ComponentType }>;
}

export interface DashboardWidgetContribution {
  type: string;       // market.overview
  titleKey: string;
  component: () => Promise<{ default: React.ComponentType }>;
}

export interface BotTemplateContribution {
  id: string;
  nameKey: string;
  descriptionKey: string;
  systemPromptKey: string;
}

export interface PluginSettingsContribution {
  id: string;
  labelKey: string;
  component: () => Promise<{ default: React.ComponentType }>;
}
```

```ts
// web/src/plugins/builtin/registry.ts

export const BUILTIN_PLUGINS: BuiltinPlugin[] = [
  {
    id: 'market-center',
    name: '市场中心',
    description: '行情、自选、板块与新闻',
    icon: 'chart-candlestick',
    version: '1.0.0',
    defaultEnabled: false,
    pages: [{
      id: 'market',
      path: '/p/market',
      labelKey: 'plugins.marketCenter.page',
      component: () => import('@/pages/MarketView/MarketView'),
    }],
    dashboardWidgets: [...],
    botTemplates: [...],
  },
];
```

### 5.2 启用状态

新增用户级数据表：

```sql
CREATE TABLE user_page_plugins (
    user_id     VARCHAR(255) NOT NULL,
    plugin_id   VARCHAR(64)  NOT NULL,
    enabled     BOOLEAN      NOT NULL DEFAULT FALSE,
    enabled_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, plugin_id)
);
```

API：

```text
GET   /api/v1/page-plugins
PATCH /api/v1/page-plugins/{plugin_id}   { enabled: true|false }
```

规则：

- 后端保存启用状态，跨设备一致。
- 后端校验 `plugin_id` 只能来自内置 allowlist。
- 前端不把启用状态只放 localStorage。
- 新用户默认全部不启用。
- 已有用户迁移策略见第 8 节。

### 5.3 动态导航

改造 `useNavItems`：

```ts
const coreItems = CORE_NAV_ITEMS; // Chat, Dashboard, Automations, Plugins
const pluginItems = enabledPlugins.flatMap(plugin =>
  plugin.pages.map(page => ({
    key: page.path,
    icon: plugin.icon,
    labelKey: page.labelKey,
    match: 'prefix',
    group: 'plugins',
  })),
);
return [...coreItems, ...pluginItems];
```

- 插件入口单独分组「已启用插件」，不能混进核心导航。
- 插件禁用时，侧栏项立即消失。
- 插件页面全部加载失败时不影响核心页面。

### 5.4 动态路由

`Main.tsx` 中：

```tsx
<Routes>
  ...coreRoutes
  <Route path="/p/:pluginId/*" element={<PluginPageHost />} />
  <Route path="/market" element={<LegacyPluginRedirect pluginId="market-center" />} />
</Routes>
```

`PluginPageHost`：

- 读取启用状态。
- 未启用：展示插件详情 + 「启用」按钮，不静默重定向。
- 已启用：渲染插件页面壳 + 对应 contribution 组件。
- 加载失败：显示错误态，不影响主应用。

### 5.5 插件页面壳

```text
┌─────────────────────────────────────────────┐
│ [icon] 市场中心  [内置插件]     [设置] [关闭]│
├─────────────────────────────────────────────┤
│ 插件自己的二级导航 / 筛选                     │
├─────────────────────────────────────────────┤
│ 内容区                                       │
└─────────────────────────────────────────────┘
```

统一头部、面包屑、错误态、加载态。

### 5.6 Dashboard 贡献

- 核心 Dashboard 只注册通用 widget：
  - 最近对话
  - 工作区
  - 定时任务
  - 用量/积分
  - 已启用插件
  - 最近文件
- 插件启用后，才把插件的 widget 注册进 Dashboard，例如：
  - `market.overview`
  - `personal.portfolioWatchlist`
  - `calendar.earnings`
- 插件禁用后，这些 widget 不显示，但用户原有配置保留，重新启用后恢复。

### 5.7 Bot 模板贡献

- 当前金融研究 Bot 模板从默认创建流程移到插件。
- 启用「研究面板」后，创建 Bot 时可看到插件提供的模板。
- 插件禁用后，不再提供新模板；已有 Bot 保留。

## 6. 页面设计

### 6.1 官网 Landing

**视觉不动**，只改内容结构：

- Hero 保留现有视觉。
- 产品展示区块改成「案例」：
  - 案例名
  - 任务描述
  - 使用的能力
  - 产物缩略图
  - 不写收益、不写买卖建议
- 增加「内置插件」介绍区块：用户可以按需启用市场/研究能力。
- CTA 仍为注册/登录。

### 6.2 Dashboard（通用工作台）

```text
┌────────────────────────────────────────────────────┐
│ 今天想让助理做什么？                                │
│ [ 输入任务… ]  [新建会话] [定时任务] [上传文件]     │
├──────────────────┬─────────────────┬───────────────┤
│ 最近对话          │ 工作区           │ 定时任务       │
│ ...              │ ...             │ ...           │
├──────────────────┼─────────────────┼───────────────┤
│ 已启用插件        │ 用量 / 积分      │ 最近文件       │
│ 市场中心          │ 100,000 credits │ ...           │
└──────────────────┴─────────────────┴───────────────┘
```

- 默认不出现行情、组合、财报日历。
- 只有启用了市场插件，才出现对应 widget。
- 保留可编辑网格能力，但插件 widget 由插件注册。

### 6.3 Chat

- 核心首页/对话入口。
- 默认欢迎语改为通用助理：
  - 研究一个主题
  - 整理文件
  - 做一个表格
  - 设置定时任务
  - 写作/总结
- 默认 Bot：Chief of Staff / 通用助理。
- 金融 Bot 模板只在研究插件启用后提供。
- 保留群聊、Bot 私聊、工作区、分享。

### 6.4 Plugins 页面

页面分两个区域：

```text
Plugins
├─ 内置插件
│  ├─ 市场中心          [启用/禁用] [设置]
│  ├─ 研究面板          [启用/禁用] [设置]
│  └─ 订单（暂不开放）   [未启用]
│
└─ 能力
   ├─ 连接器（MCP）
   ├─ 技能
   └─ 子 Agent
```

- 内置插件卡片：图标、名称、描述、包含内容、版本、启用开关。
- 「启用」后侧栏出现入口。
- 不提供卸载代码，只提供禁用。
- 现有第三方 MCP/技能安装保留在「能力」区域；页面插件不开放第三方。若后续要求完全关闭第三方安装，再单独做开关。

### 6.5 市场中心插件页

```text
┌────────────────────────────────────────────────────┐
│ 📈 市场中心  [内置插件]                    [设置]  │
├────────────────────────────────────────────────────┤
│ 概览 | 自选 | 板块 | 新闻                           │
├───────────────────────────┬────────────────────────┤
│ 指数概览                   │ 自选列表               │
├───────────────────────────┼────────────────────────┤
│ K 线主图                   │ 新闻 / 财报日历        │
└───────────────────────────┴────────────────────────┘
```

- 优先复用现有 `MarketView` 数据层与组件，只改变入口和壳。
- 旧链接 `/market` 可用时重定向。
- 未启用时访问 `/p/market` 显示插件详情和启用按钮。

### 6.6 Settings

核心设置：

```text
账户
助理偏好（非投资）
外观
对话
模型
套餐与用量
隐私
```

下沉到插件：

- 投资画像 → 研究插件设置
- 行情偏好 → 市场中心插件设置
- 交易权限 → 订单插件设置

### 6.7 Onboarding

- 已停止自动弹出投资偏好问卷（本次已修）。
- 新用户首次进入只做轻量引导：
  - 欢迎
  - 选择主要用途：工作 / 研究 / 写作 / 自动化
  - 可跳过
- 金融问卷只在启用研究插件后出现。

### 6.8 Orders

- 默认不开放。
- 如果保留，作为 `orders` 内置插件，默认禁用。
- 不宣传交易执行能力，不接公开下单入口，不输出买卖建议。

## 7. 合规与内容

- 核心页面、官网、默认 Bot 提示词不使用：
  - 金融 Agent
  - 投资顾问
  - 荐股
  - 买卖建议
  - 收益承诺
- 插件名称使用中性词：
  - 市场中心
  - 研究面板
  - 数据工具
- 所有 AI 输出继续保留「AI 生成，不构成投资建议」。
- 案例页只展示任务和产物，不展示收益。
- 插件条款、数据授权、第三方数据来源单独说明。
- 即使插件可选，也不能把插件宣传成持牌投顾服务。

## 8. 迁移与发布

### Phase 0：设计评审（本 PR）

交付：

- 页面盘点
- 目标 IA
- 内置插件协议
- 页面布局
- 合规边界
- 验收清单

### Phase 1：核心壳去金融化

- 核心导航只留 Chat / Dashboard / Automations / Plugins。
- Dashboard 改成通用工作台。
- 移除默认金融 widget。
- Chat 默认提示词/Bot 通用化。
- Settings 移除投资画像、交易入口。
- 验收：新用户看不到行情/投资问卷。

### Phase 2：内置插件框架 + 市场中心

- 新增 `user_page_plugins` 表和 API。
- 新增 builtin registry、PluginPageHost、动态导航。
- 把 MarketView 抽成 `market-center` 插件。
- Dashboard 金融 widget 变成插件贡献。
- Plugins 页新增「内置插件」区域。
- 验收：启用/禁用可逆、刷新持久、旧链接可用。

### Phase 3：内容与案例页

- Landing 视觉不动，文案/区块改为案例页。
- 研究插件设置、Bot 模板迁移。
- 全站文案审查。

### 已有用户迁移

推荐策略：

- 新用户：默认全部插件关闭。
- 已有用户：
  - 有行情/组合/自选/订单数据的账号，首次升级时**自动启用市场插件**，并显示一次「市场中心已移到插件」提示；
  - 其余账号默认关闭。
- 不做静默删除；保留数据与旧链接。

## 9. 验收清单

- [ ] 新用户注册后直接进入 Dashboard，不出现投资偏好问卷。
- [ ] 核心导航只有 Chat / Dashboard / Automations / Plugins。
- [ ] 默认 Dashboard 没有行情、组合、财报 widget。
- [ ] Plugins 页显示内置插件卡片，默认关闭。
- [ ] 启用市场中心后侧栏出现入口，页面可打开。
- [ ] 禁用后入口消失，直接访问 `/p/market` 显示启用提示。
- [ ] 启用状态刷新后保留，换设备一致。
- [ ] `/market` 旧链接在启用时重定向，未启用时落到插件详情。
- [ ] 插件页面失败不影响核心页面。
- [ ] 核心页面文案无「投资顾问/荐股/收益承诺」。
- [ ] 案例页不出现收益承诺或买卖建议。

## 10. 风险与开放问题

### 风险

- 老用户找不到 Market：用一次性提示 + 自动启用策略缓解。
- Dashboard 通用化后信息密度下降：用最近会话/工作区/任务/用量填充。
- 插件状态与路由不一致：以服务端状态为唯一来源，前端不缓存为权威。
- 合规只靠页面命名不够：仍需业务实质、条款、数据授权和法务评审。

### 开放问题

1. 已有用户是否自动启用市场中心？建议仅对有用量/数据的账号启用。
2. Orders 是第一期插件，还是暂不开放？
3. 研究插件是否包含投资画像问卷，还是只保留通用助理偏好？
4. 现有 MCP/技能第三方安装是否保留？建议保留为「连接器」，页面插件不开放第三方。
5. 插件启用粒度是用户级还是工作区级？一期建议用户级。

## 11. 涉及代码位置

| 模块 | 位置 |
|---|---|
| 导航 | `web/src/components/nav/navItems.ts`、`useNavItems.ts` |
| 主路由 | `web/src/components/Main/Main.tsx`、`web/src/lib/appRoutes.ts` |
| Dashboard | `web/src/pages/Dashboard`、`widgets/presets.ts` |
| 市场页 | `web/src/pages/MarketView` |
| 插件页 | `web/src/pages/Plugins` |
| 设置 | `web/src/pages/Settings` |
| Onboarding | `web/src/pages/Onboarding` |
| 后端插件 | `src/server/app/plugins.py`、`src/server/database/plugins.py` |
| 后端路由 | `src/server/app` |

## 12. 结论

不需要重写整个应用，核心改造是：

1. 把「页面入口」从静态路由/导航变成内置插件注册表。
2. 把金融页面从核心导航移到插件，默认关闭。
3. 把 Dashboard 从金融看板改成通用助理工作台。
4. 把官网视觉保留，内容改成案例展示。

这样产品对外是「云端 Bot 助理」，金融能力是用户主动启用的内置工具，既保留现有能力，又降低合规和定位风险。
