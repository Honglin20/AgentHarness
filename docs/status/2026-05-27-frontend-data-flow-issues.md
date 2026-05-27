# 前端数据流三大缺陷 — 完整诊断文档

> **优先级**: P0
> **日期**: 2026-05-27
> **影响**: 核心用户流程完全不可用

---

## 三个缺陷

### Bug 1: 实时对话不可见
- **现象**: workflow 启动后运行过程中，Conversation 标签页空白，无流式输出
- **影响**: 用户无法实时观察 agent 执行过程

### Bug 2: Charts 不显示
- **现象**: workflow 完成后 Results 标签页为空，图表不渲染
- **影响**: 用户无法查看 agent 输出的可视化结果

### Bug 3: Collapsible 不可交互
- **现象**: 点击图表组标题行无法收起/展开
- **影响**: UI 交互受限（此 bug 已有代码修复但未验证生效）

---

## 架构背景

### 双路径架构（当前状态）

```
Landing Page:
  WorkflowCenterPanel → (workflowId=null) → CenterPanel (legacy)
    → useWorkflowEvents → 全局 stores → 全局组件

Live Mode (workflow 启动后):
  WorkflowCenterPanel → (workflowId=xxx) → WorkflowScope → ScopedCenterPanel
    → useWorkflowWS → eventRouter → scoped stores → scoped 组件

Replay Mode (点击已完成 run):
  WorkflowCenterPanel → (workflowId=runId) → WorkflowScope → ScopedCenterPanel
    → viewStore.showReplay → replayEvents/loadLegacyData → scoped stores
```

### 关键组件

| 组件 | 文件 | 职责 |
|------|------|------|
| WorkflowCenterPanel | `components/layout/WorkflowCenterPanel.tsx` | 决定用 legacy 还是 scoped |
| CenterPanel | `components/layout/CenterPanel.tsx` | Legacy：landing page + 直接 WebSocket |
| ScopedCenterPanel | `components/layout/ScopedCenterPanel.tsx` | Scoped：通过 context stores 渲染 |
| useWorkflowEvents | `hooks/useWorkflowEvents.ts` | Legacy 事件路由 → 全局 stores |
| useWorkflowWS | `contexts/workflow-context/useWorkflowWS.ts` | Scoped WebSocket 管理 |
| eventRouter | `contexts/workflow-context/eventRouter.ts` | Scoped 事件路由 → scoped stores |
| WorkflowScope | `contexts/workflow-context/WorkflowScope.tsx` | 创建 scoped stores 并提供 context |
| WorkflowManager | `contexts/workflow-context/WorkflowManager.ts` | 管理 workflow 生命周期和 stores |

### 事件流路径

```
后端 EventBus → WebSocket → useWebSocket.onmessage → onEvent callback
  → dispatchSingleEvent(event, currentWorkflowId)
    → routeEventToStores(event)
      → manager.getStores(wid) → scoped stores → React re-render
```

---

## 已完成的改动

### Phase 1: 后端（已验证，215/215 测试通过）

| 提交 | 改动 | 状态 |
|------|------|------|
| `563143b` | RunStore 新增 events 字段 | ✅ 正确 |
| `25a40f3` | runner.py 用 ConversationCollector 替代 build_conversation | ✅ 正确 |
| `74338e0` | ConversationCollector 集成测试 | ✅ 正确 |
| `f0c3943` | EventBus buffer 500→2000 | ✅ 正确 |
| `da60832` | runner.py 无 EventBus 时 fallback | ✅ 正确 |

验证：最近一次 run 文件有 387 个 events，13 条 conversation，chart_groups 存在。

### Phase 2: 前端（仍不工作）

| 提交 | 改动 | 状态 |
|------|------|------|
| `41df44a` | 新建 replayEvents.ts | 代码正确但依赖事件能到达 stores |
| `548786f` | viewStore.showReplay 回放事件 | 未验证 |
| `ff7a1ad` | RunRecord 类型加 events | 正确 |
| `b2858a9` | Collapsible localCollapsed | 未验证 |
| `548786f` | WorkflowCenterPanel 统一渲染 | 引入 WSMethodProvider 崩溃 |
| `edd093a` | 修复 WSMethodProvider 崩溃 | ✅ 崩溃修复 |
| `d37dd26` | useWorkflowWS 用 workflowId 替代全局 store | 核心修复但未生效 |

---

## 根因分析（待验证）

### 假设 1: 渲染切换时序问题
当从 landing page (CenterPanel) 启动 workflow 时：
1. CenterPanel.startWorkflow() → setWorkflow(id) 全局 store
2. WorkflowCenterPanel 重新渲染 → 从 CenterPanel 切换到 WorkflowScope + ScopedCenterPanel
3. CenterPanel 卸载 → useWorkflowEvents 断开
4. WorkflowScope 创建 scoped stores (useMemo)
5. useWorkflowWS 连接 WebSocket (useEffect)
6. WebSocket 接收 EventBus buffer replay
7. 事件通过 eventRouter 路由到 scoped stores

**可能断裂点**: 步骤 2-4 之间事件丢失，或步骤 5-7 之间 stores 未正确初始化

### 假设 2: 全局/Scoped store 不一致
- CenterPanel.startWorkflow() 调用全局 store 的 setWorkflow()
- ScopedCenterPanel 读取 scoped store
- 两者可能不同步

### 假设 3: 事件根本没到达前端
- WebSocket 可能连接了但没收到事件
- 需要检查浏览器 DevTools Network → WS 标签

---

## 下一步：调试策略

### 必须在浏览器中验证

**不要猜测，用数据驱动：**

1. **打开 DevTools Console** — 搜索 `[EventRouter]` 警告。如果看到 `No workflow entry found`，说明 stores 在事件到达时不存在
2. **打开 DevTools Network → WS** — 查看 WebSocket 连接是否建立，是否有消息到达
3. **在 Console 执行** `getWorkflowManager().getActiveWorkflow()` — 检查 scoped stores 状态
4. **在 eventRouter.routeEventToStores 入口加 console.log** — 确认事件是否到达

### 具体调试步骤

```typescript
// 在 eventRouter.ts 的 routeEventToStores 函数开头临时添加：
console.log('[routeEventToStores]', event.type, 'wid:', wid,
  'stores:', !!stores, 'msgs:', stores?.conversation?.getState()?.messages?.length);
```

### 如果需要回退
```bash
# 只回退前端改动，保留后端
git revert <frontend-commits> --no-commit
# 或手动恢复 WorkflowCenterPanel.tsx 到改前版本
```

---

## 技术债务

1. **两套事件路由并行存在**: useWorkflowEvents (legacy) 和 eventRouter (scoped) 功能重复
2. **两套组件并行存在**: ConversationTab/ScopedConversationTab 等
3. **全局 store 和 scoped store 混用**: useWorkflowStore.workflowId (全局) vs scoped workflow store
4. **没有前端测试**: 所有验证依赖手动测试
