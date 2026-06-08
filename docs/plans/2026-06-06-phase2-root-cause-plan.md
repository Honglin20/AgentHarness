# Phase 2 根因分析与架构改进计划

> 日期: 2026-06-06
> 前置: Phase 1 (P0 紧急修复) 已完成
> 目标: 从根本上解决架构缺陷，不是修补 bug，而是消除产生 bug 的土壤

---

## 一、根因诊断

> 审查报告描述了 5 大类问题（巨型文件、循环依赖、事件路由、组件质量、鲁棒性）。
> 这些是 **症状**，不是根因。以下是 5 个真正的根因。

### 根因 1: 双轨 Store 架构 — 全局 Store 与 Scoped Store 共存，无权威数据源

**症状表现:**
- `userStore.ts:resetAllStores()` 重置全局 store 但对 scoped store 无感知
- `ScopedCenterPanel.startWorkflow()` 同时写全局 store 和 scoped store
- `types.ts` 和 `workflowStores.ts` 各自定义了 `WorkflowStores` 接口

**代码证据:**

```
userStore.ts:28-43  — resetAllStores() 只操作全局 store
ScopedCenterPanel.tsx:203-208 — startWorkflow 同时写两套 store:
  newStores.workflow.getState().setWorkflow(...)  // scoped
  useWorkflowStore.getState().setWorkflow(...)     // 全局
```

**为什么这是根因:**
系统有两个独立的数据源，没有任何机制保证一致性。用户切换、重置、并发操作时，两套 store 必然出现不一致。这不是 "修一个 bug" 能解决的 — 每次 grow 功能都会制造新的不一致路径。

**设计原则违背:**
- Single Source of Truth (SSOT)
- Single Responsibility Principle

---

### 根因 2: 事件路由违反开闭原则 — 500 行 switch 不可扩展

**症状表现:**
- `routeEvent.ts` 是一个 500 行的巨型 switch
- 添加新事件类型必须修改此文件（违反 OCP）
- `payload<T>()` 用 `as unknown as T` 完全绕过类型安全

**代码证据:**

```typescript
// routeEvent.ts:91-93 — 类型安全完全被绕过
function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

// 30+ case 分支，每个直接操作多个 store
case "node.completed": {
  stores.workflow.getState().handleNodeCompleted(p);
  stores.conversation.getState().completeAgentMessage(...);
  stores.agentIO.getState().setAgentIO(...);
  // ... 50+ 行逻辑
}
```

**为什么这是根因:**
扁平 switch 把 "识别事件类型" 和 "执行业务逻辑" 耦合在一起。每次新增事件类型（如 `todo.*`、`span.*`）都是一次侵入式修改。随着事件类型增长，文件复杂度指数增长。去重逻辑 (`_processedSeqsByWorkflow`) 与路由逻辑混杂，违反 SRP。

**设计原则违背:**
- Open/Closed Principle (OCP)
- Single Responsibility Principle (SRP)
- Type Safety

---

### 根因 3: Store 工厂内嵌业务逻辑 — 1,513 行巨型文件是结构问题的必然结果

**症状表现:**
- `workflowStores.ts` 1,513 行：9 个 store 工厂 + RAF 批处理 + 缓存管理 + 计数器
- 每个内联 `initialState` 先声明空 stub，再声明真实实现 — two-pass definition
- RAF 批处理在 `createConversationStore` 和 `createOutputStore` 中几乎完全复制

**代码证据:**

```typescript
// workflowStores.ts 的每个 store 都有这个模式:
const initialState = {
  // ... 空实现 stub
  addSystemMessage: (content) => { /* Phase 2 实现 */ },
  addAgentMessage: (nodeId, agentName) => { /* Phase 2 实现 */ },
  // ... 15+ 个空方法
};

return createStore<ConversationState>()((set, get) => ({
  ...initialState,
  // ... 500 行真实实现覆盖上面的 stub
}));
```

更严重的是缓存管理：每个 store 都有 `saveToCache`/`restoreFromCache`/`setActiveWid`/`clearCache` 四个方法。9 个 store × 4 个方法 = **36 个近乎相同的实现**。

**为什么这是根因:**
Store 应该只定义状态形状和基础 mutation。RAF 批处理、缓存管理、计数器生成是横切关注点，应该通过组合（composition）而非复制（copy-paste）实现。当前结构使得任何横切关注点的修改都需要改 9 个地方。

**设计原则违背:**
- DRY (Don't Repeat Yourself)
- Composition over Inheritance
- SRP

---

### 根因 4: 循环依赖 — Store 层与 Context 层双向耦合

**症状表现:**
- `stores/userStore.ts` → import `setActiveWorkflowId` from `contexts/workflow-context`
- `contexts/workflow-context/WorkflowScope.tsx` → 间接引用 `stores/*`
- `contexts/workflow-context/workflowStores.ts` → import types from `stores/*`

**依赖链:**

```
stores/userStore.ts ──→ contexts/workflow-context (setActiveWorkflowId)
       ↑                            ↓
       │                   WorkflowScope → stores/userStore
       │                            ↓
       ←── workflowStores.ts ←── stores/conversationStore (types)
```

**为什么这是根因:**
循环依赖意味着两个模块不能独立测试、独立演进。任何一方的修改都可能意外破坏另一方。这也是为什么 "简单拆分 workflowStores.ts" 不能真正解决问题 — 拆了文件，依赖关系没变。

**设计原则违背:**
- Dependency Inversion Principle (DIP)
- Layered Architecture

---

### 根因 5: God Component — ScopedCenterPanel 违反单一职责

**症状表现:**
- 470 行，3 个完全不同的渲染路径（benchmark/portal/normal）
- 包含业务逻辑 (`startWorkflow`, `handleSaveBenchmark`)
- 读取 15+ 个不同 hooks/stores
- 混合了路由、CRUD、状态管理、UI 渲染

**代码证据:**

```
ScopedCenterPanel.tsx:
  - L222-333: benchmark 视图（111 行）
  - L337-346: error 状态（10 行）
  - L349-373: portal/landing（25 行）
  - L378-473: normal 视图（95 行）
  - L171-214: startWorkflow 业务逻辑（43 行）
  - L158-169: handleSaveBenchmark 业务逻辑（12 行）
```

**为什么这是根因:**
God Component 是其他所有根因的汇聚点。它同时依赖全局 store 和 scoped store（根因 1），直接调用事件处理逻辑（根因 2），内联业务逻辑而非提取到 hook（根因 3），双向依赖导致无法拆分（根因 4）。

**设计原则违背:**
- SRP
- Separation of Concerns
- Presentational/Container 分离

---

## 二、根因关系图

```
根因 4: 循环依赖 (最底层)
    ↓ 阻碍了
根因 1: 双轨 Store (数据一致性)
    ↓ 导致了
根因 3: Store 工厂膨胀 (横切关注点重复)
    ↓ 积累了
根因 2: 事件路由巨型 switch (OCP 违反)
    ↓ 表现为
根因 5: God Component (所有问题的汇聚)
```

**关键洞察:** 根因 4 是地基问题。不解决循环依赖，其他重构都是换位置而不换结构。

---

## 三、改进计划

> 原则: 自底向上修复。每一步是下一步的基础。每步完成后可独立验证。

### Step 1: 消除循环依赖 — 建立单向依赖层

**目标:** Store → Context 变为 Store ← Context（单向）

**具体方案:**

1a. 提取 `setActiveWorkflowId` 到 `lib/workflowNavigation.ts`

```
// 现在:
stores/userStore.ts → import { setActiveWorkflowId } from contexts/workflow-context
// 目标:
stores/userStore.ts → import { resetGlobalStores } from stores/resetAllStores.ts
lib/workflowNavigation.ts → 调用 WorkflowManager.setActiveWorkflowId (只有 UI 层调用)
```

1b. 提取 `resetAllStores` 到 `stores/resetGlobalStores.ts`

将 `userStore.ts:28-43` 的 `resetAllStores()` 移出。它只操作全局 store，不应依赖 workflow-context。

1c. workflowStores.ts 只 import type（不 import value）

将 `stores/*` 的类型导入改为 `import type` — 运行时零耦合。

**验证:**
- `madge --circular frontend/src/` 输出 0 个循环
- `npm run build` 通过
- 所有现有测试通过

**工作量:** 0.5 天
**风险:** 低 — 纯重排 import，不改逻辑

---

### Step 2: 统一 Store 架构 — Scoped Store 为唯一数据源

**目标:** 消除双轨 Store，让 scoped store 成为唯一真相源

**具体方案:**

2a. 全局 store 降级为 "路由层"

全局 store（`workflowStore`, `conversationStore` 等）不再存储数据，仅作为 "哪个 workflow 是活跃的" 的路由信号。数据全部走 scoped store。

```
// 现在:
useWorkflowStore.getState().setWorkflow(id, name, dag)  // 存数据
// 目标:
useWorkflowStore.getState().setActiveId(id)  // 只路由
// 数据通过:
getWorkflowManager().getOrCreate(id).stores.workflow.getState().setWorkflow(...)
```

2b. userStore.resetAllStores() 改为通过 WorkflowManager 清理

```typescript
// 目标:
function resetAllStores() {
  getWorkflowManager().reset();  // 清理所有 scoped stores
  // 全局路由层也重置
  useWorkflowStore.getState().setActiveId(null);
  // ...
}
```

2c. ScopedCenterPanel.startWorkflow 只写 scoped store

移除 `useWorkflowStore.getState().setWorkflow(...)` 调用。全局 store 只接收 `setActiveId`。

**验证:**
- 切换用户 → 所有 store 正确清空
- 并行 workflow → 输出不再互相干扰
- 刷新 → REST pre-populate 填充 scoped store，全局 store 只存 activeId

**工作量:** 2 天
**风险:** 中 — 涉及全局 store 的所有消费者

---

### Step 3: 提取横切关注点 — 消除 Store 工厂中的重复代码

**目标:** workflowStores.ts 拆分时没有重复代码可拆

**具体方案:**

3a. RAF 批处理器 → `lib/rafBatcher.ts`

```typescript
export function createRafBatcher<TKey, TValue>(
  apply: (updates: Map<TKey, TValue>) => void,
): {
  push: (key: TKey, value: TValue, merge: (prev: TValue, next: TValue) => TValue) => void;
  flush: () => void;
  cancel: () => void;
} { ... }
```

Conversation store 和 Output store 各创建一个实例，消除 ~120 行重复代码。

3b. 缓存管理器 → `lib/storeCache.ts`

```typescript
export function withCache<T extends Record<string, unknown>>(
  store: StoreApi<T>,
  options: { maxEntries?: number } = {},
): {
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
} { ... }
```

消除 36 个近乎相同的缓存方法。

3c. ID 计数器 → `lib/idCounter.ts`

提取 `createMessageCounter` 和 `createToolCallCounter` 到独立模块。

**验证:**
- 对话消息 ID 仍然唯一递增
- Tab 切换时缓存正确保存/恢复
- RAF 批处理行为不变

**工作量:** 1 天
**风险:** 低 — 纯提取，不改变行为

---

### Step 4: 拆分 workflowStores.ts — 一文件一 Store

**目标:** 1,513 行拆为 ~10 个文件，每个 < 200 行

**目标结构:**

```
contexts/workflow-context/stores/
├── index.ts                  # createWorkflowStores 导出
├── conversation.ts           # ~200 行（含 RAF 批处理引用）
├── output.ts                 # ~120 行
├── workflow.ts               # ~150 行
├── chart.ts                  # ~80 行
├── toolCall.ts               # ~80 行
├── agentIO.ts                # ~50 行
├── chat.ts                   # ~60 行
├── span.ts                   # ~80 行
└── todo.ts                   # ~80 行
```

**验证:**
- 所有 import 路径更新，`npm run build` 通过
- 每个 store 独立可测试

**工作量:** 1 天
**风险:** 低 — 在 Step 3 之后做，每个 store 文件已经很精简

---

### Step 5: 事件路由重构 — 注册表模式

**目标:** 从 500 行 switch → 可扩展的事件处理器注册表

**具体方案:**

5a. 定义事件处理器接口

```typescript
// routing/EventHandler.ts
interface EventHandler<TPayload> {
  eventType: string;
  handle(stores: WorkflowStores, payload: TPayload, ctx: RouteContext): void;
}
```

5b. 按领域拆分处理器

```
contexts/workflow-context/routing/
├── index.ts                  # routeEvent 入口 + dedup 中间件
├── registry.ts               # 事件注册表
├── middleware/
│   ├── dedup.ts              # 去重中间件（从 routeEvent.ts 提取）
│   └── logging.ts            # 错误日志中间件
├── handlers/
│   ├── workflowHandlers.ts   # workflow.started/completed/error/cancelled
│   ├── nodeHandlers.ts       # node.started/completed/failed
│   ├── agentHandlers.ts      # agent.text_delta/thinking_delta/tool_*
│   ├── chatHandlers.ts       # chat.question/answer, followup.*
│   ├── chartHandlers.ts      # chart.render
│   ├── todoHandlers.ts       # todo.created/updated
│   └── spanHandlers.ts       # span.start/end
└── utils.ts                  # formatOutputAsMd, resetAllStores
```

5c. 去重逻辑独立为中间件

```typescript
// dedup.ts
function withDedup(handler: EventHandler): EventHandler {
  return {
    eventType: handler.eventType,
    handle(stores, event, ctx) {
      if (isDuplicate(stores, event)) return;
      handler.handle(stores, event, ctx);
    }
  };
}
```

5d. 类型安全的 payload 提取

```typescript
// 用 zod 或 TypeScript discriminated union 替代 as unknown as T
type EventPayloadMap = {
  "workflow.started": WorkflowStartedPayload;
  "node.completed": NodeCompletedPayload;
  // ...
};

function getPayload<T extends WSEvent["type"]>(
  event: WSEvent & { type: T }
): EventPayloadMap[T] {
  return event.payload as EventPayloadMap[T];  // 单点类型断言
}
```

**验证:**
- 添加新事件类型只需新增 handler 文件，不修改任何现有文件
- 去重逻辑可通过单元测试独立验证
- `npm run build` 通过

**工作量:** 2 天
**风险:** 中 — 核心路径重构，需要仔细测试每个事件类型

---

### Step 6: 分解 God Component

**目标:** ScopedCenterPanel 470 行 → 多个 < 150 行的专职组件

**具体方案:**

6a. 提取自定义 hooks

```typescript
// hooks/useWorkflowLaunch.ts — startWorkflow 逻辑
// hooks/useBenchmarkManager.ts — benchmark CRUD 逻辑
```

6b. 按视图模式拆分组件

```
components/center-panel/
├── CenterPanelRouter.tsx     # ~30 行，纯路由
├── NormalView.tsx            # ~100 行，普通 workflow 视图
├── BenchmarkView.tsx         # ~100 行，benchmark 视图
├── PortalView.tsx            # ~50 行，landing/portal 视图
├── ErrorView.tsx             # ~20 行
└── TabBar.tsx                # ~40 行，tab 导航
```

**验证:**
- 每个组件 < 150 行
- 每个 hook 只负责一个关注点
- 视觉无变化

**工作量:** 1.5 天
**风险:** 低 — 纯拆分，不改逻辑

---

## 四、实施顺序与依赖

```
Step 1: 消除循环依赖         ← 基础，无依赖
   ↓
Step 2: 统一 Store 架构      ← 依赖 Step 1 的单向依赖层
   ↓
Step 3: 提取横切关注点       ← 依赖 Step 2 的 store 结构
   ↓
Step 4: 拆分 workflowStores  ← 依赖 Step 3 的共享模块
   ↓ (可并行)
Step 5: 事件路由注册表       ← 依赖 Step 1 的依赖层
Step 6: 分解 God Component   ← 依赖 Step 2 的统一 store
```

**总工作量:** 8 天（~1.5 周）

**建议节奏:**
- Step 1-2: 第 1 周（核心架构修复）
- Step 3-4: 第 2 周 前 3 天（store 拆分）
- Step 5-6: 第 2 周 后 2 天（路由 + 组件）

每个 Step 完成后:
1. `npm run build` 通过
2. `pytest` 通过
3. 手动验证核心流程（启动 workflow、切换历史、benchmark）
4. git commit（原子提交）

---

## 五、风险与回退策略

| 风险 | 概率 | 缓解 |
|------|------|------|
| Step 2 统一 store 引入回归 | 中 | 渐进式迁移：先新增 "只写 scoped" 路径，旧路径保留，验证后移除 |
| Step 5 路由重构漏掉事件类型 | 低 | 先写映射表（30 个事件 → 30 个 handler），逐一迁移，每个 handler 独立测试 |
| Step 4 拆分导致 import 混乱 | 低 | 使用 barrel file (`index.ts`) 保持外部 API 不变 |
| 并行 workflow 回归 | 中 | Step 2 完成后做 E2E 并行测试 |

**回退原则:** 每个 Step 是独立 commit。如果某 Step 出问题，revert 该 commit 即可回退，不影响其他 Step。

---

## 六、成功标准

| 指标 | 当前 | 目标 |
|------|------|------|
| 循环依赖数 | 3+ | 0 |
| 最大单文件行数 | 1,513 | < 200 |
| 全局/Scoped 双写点 | 5+ | 0 |
| 事件路由可扩展性 | 修改 switch | 新增 handler 文件 |
| 新增事件类型改动文件数 | 2-3 | 1 |
| God Component 行数 | 470 | < 150 |

---

## 七、与原审查报告的对应关系

| 审查报告问题 | 根因 | 对应 Step |
|-------------|------|----------|
| 2.1 巨型文件 | 根因 3: 横切关注点重复 | Step 3 + 4 |
| 2.2 循环依赖 | 根因 4: 双向耦合 | Step 1 |
| 3.1 历史记录消失 | 根因 1: 双轨 Store | Phase 1 已修 |
| 3.2 并行干扰 | 根因 1: 双轨 Store | Step 2 |
| 3.3 全局/Scoped 冲突 | 根因 1: 双轨 Store | Step 2 |
| 4.2 事件丢失 | 根因 2: switch 不可维护 | Step 5 |
| 5.3 代码重复 | 根因 3: 横切关注点重复 | Step 3 |
| 6.1 崩溃路径 | 根因 1+2: 不一致 + 不安全 | Step 2 + 5 |
