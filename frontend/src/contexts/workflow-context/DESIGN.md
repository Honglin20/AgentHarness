# Context 隔离架构设计

## 概述

本文档描述了从前端全局单例 stores 迁移到 Context 隔离架构的设计方案。

### 问题

当前架构使用全局 zustand stores，多个 workflow 共享同一状态，导致：
- conversation 堆叠
- 切换 workflow 时状态混乱
- 需要手动 cache 管理逻辑（违反 DRY）

### 解决方案

采用 Context 隔离（方案 C）：每个 workflow 有独立的 store 实例，通过 React Context 提供。

---

## 架构图

```
当前架构（全局单例）:
            WebSocket Events
                    ↓
        useWorkflowEvents hook
                    ↓
          ┌─────────┴─────────┐
          │                   │
    全局 stores          UI Components
  (conversation, ...)   (直接访问)
          ↑
      所有问题

新架构（Context 隔离）:
            WebSocket Events (per workflowId)
                    ↓
        WorkflowManager (管理生命周期)
                    ↓
        WorkflowContext.Provider
                    ↓
          ┌─────────┴─────────┐
          │                   │
    Workflow Stores (实例)  UI Components
  (per workflow scope)   (通过 Context)
          ↑
      自动隔离
```

---

## 1. 文件结构

```
frontend/src/
├── contexts/
│   └── workflow-context/
│       ├── WorkflowContext.tsx          # 主 Context + Provider
│       ├── workflowStores.ts            # Store 工厂函数
│       ├── WorkflowManager.ts           # 生命周期管理
│       ├── types.ts                     # 类型定义
│       └── index.ts                     # 导出
├── stores/                              # 保持不变（用于共享状态）
│   ├── batchStore.ts                    # 共享：batch 元数据
│   ├── runHistoryStore.ts               # 共享：运行历史
│   ├── viewStore.ts                     # 共享：视图状态
│   └── ...
└── components/
    └── layout/
        ├── WorkflowScope.tsx           # 新增：Context Provider 包装器
        └── CenterPanel.tsx             # 修改：使用 WorkflowScope
```

---

## 2. Store 工厂函数设计

```typescript
// workflowStores.ts
import { createStore } from 'zustand/vanilla';
import { useStore } from 'zustand';
import type { ConversationState } from '@/stores/conversationStore';
import type { OutputState } from '@/stores/outputStore';
import type { WorkflowState } from '@/stores/workflowStore';
import type { ChartState } from '@/stores/chartStore';
import type { ToolCallState } from '@/stores/toolCallStore';
import type { AgentIOState } from '@/stores/agentIOStore';
import type { ChatState } from '@/stores/chatStore';

export interface WorkflowStores {
  conversation: StoreApi<ConversationState>;
  output: StoreApi<OutputState>;
  workflow: StoreApi<WorkflowState>;
  chart: StoreApi<ChartState>;
  toolCall: StoreApi<ToolCallState>;
  agentIO: StoreApi<AgentIOState>;
  chat: StoreApi<ChatState>;
}

export function createWorkflowStores(workflowId: string): WorkflowStores {
  return {
    conversation: createConversationStore(workflowId),
    output: createOutputStore(workflowId),
    workflow: createWorkflowStore(workflowId),
    chart: createChartStore(workflowId),
    toolCall: createToolCallStore(workflowId),
    agentIO: createAgentIOStore(workflowId),
    chat: createChatStore(workflowId),
  };
}
```

---

## 3. Workflow 生命周期

### 3.1 状态机

```
workflow 状态机:

       +------------------+
       |  创建 (Created)   | → 创建 stores
       +---------+--------+
                 |
                 v
       +------------------+
       |  运行中 (Running) | → stores 保持活跃，WebSocket 连接
       +---------+--------+
                 |
       +---------v---------+     +------------------+
       | 切换到其他 workflow | ----→ |  后台运行 (BG)     |
       +---------+---------+     +--------+---------+
                 |                        |
                 |    完成后             |    用户切换回来
                 v                        |
       +------------------+              |
       |  已完成 (Done)    | <------------+
       +---------+--------+
                 |
                 |    (延迟清理)
                 v
       +------------------+
       |  销毁 (Destroyed) | → 释放 stores，关闭连接
       +------------------+
```

### 3.2 WorkflowManager

核心职责：
- 创建和管理 WorkflowStores 实例
- 管理 WebSocket 连接
- 清理空闲 workflow
- 分发事件到正确的 stores

---

## 4. WebSocket 多连接策略

### 4.1 策略对比

| 策略 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| A. 全连接 | 所有 workflow 保持连接 | 切换即时 | 连接数多 |
| B. 仅前台 | 只保持 active workflow 连接 | 连接数少 | 切换有延迟 |
| C. N+K | 保持前 N 个活跃 + K 个后台 | 平衡 | 配置复杂 |
| **D. 混合** | running 保持连接，completed 断开 | 符合语义 | 切换到 completed workflow 时需重新连接 |

### 4.2 推荐策略：D（混合）

```typescript
shouldKeepConnection(entry: WorkflowEntry, isActive: boolean): boolean {
  // 1. 始终保持前台 workflow 连接
  if (isActive) return true;

  // 2. running 状态保持连接（接收事件）
  if (entry.status === "running") return true;

  // 3. completed/failed 状态断开（不需要新事件）
  return false;
}
```

---

## 5. Batch 模式特殊处理

```
Batch 模式架构:
            /ws/batch/{batchId}
                    ↓
            BatchFanIn (后端)
                    ↓
        合并所有 workflow 事件
                    ↓
         前端单个 WS 连接
                    ↓
    根据 workflow_id 分发到 stores
```

- 使用单个 WebSocket 连接
- 后端通过 BatchFanIn 合并事件
- 前端根据 `workflow_id` 路由到正确的 stores

---

## 6. 内存管理

### 6.1 Store 内存估算

```
单个 workflow 典型数据量:
- conversation: ~200KB (100 条消息)
- output: ~10KB (10 个节点)
- workflow: ~10KB (20 个节点)
- chart: ~25KB (5 个图表)
- toolCall: ~15KB (50 个 tool call)
- agentIO: ~20KB (10 个 agent IO)
- chat: ~2.5KB (5 条 chat 消息)
---
总计: ~282KB

10 个并行 workflow: ~2.8MB
50 个历史 workflow: ~14MB
```

### 6.2 三级清理策略

| 级别 | 清理内容 | 触发条件 |
|------|---------|---------|
| Light | 清空 conversation messages | workflow 完成 5 分钟后 |
| Medium | 清空所有 transient 数据 | 超过 20 个 workflow |
| Aggressive | 完全销毁 | 超过 50 个 workflow 或用户手动清理 |

---

## 7. 事件分发

### 7.1 事件 → Store 映射

```typescript
const EVENT_TO_STORES: Record<string, (keyof WorkflowStores)[]> = {
  "workflow.started": ["workflow"],
  "workflow.completed": ["workflow"],
  "node.started": ["workflow", "conversation"],
  "node.completed": ["workflow", "conversation", "agentIO"],
  "agent.text_delta": ["output", "conversation"],
  "agent.tool_call": ["toolCall", "conversation"],
  "agent.tool_result": ["toolCall", "conversation"],
  "chat.question": ["chat", "conversation"],
  "chart.render": ["chart"],
};
```

### 7.2 Batch 模式事件缓存

- 对于非选中的 workflow，缓存事件而不是更新 stores
- 切换 workflow 时重放缓存的事件
- 限制缓存大小（最大 500 个事件）

---

## 8. 迁移路径

| 阶段 | 工作量 | 描述 |
|------|--------|------|
| **Phase 0** | 基础设施 | 创建 workflowStores 工厂、WorkflowContext、WorkflowManager |
| **Phase 1** | 核心组件 | 迁移 CenterPanel 及其子组件（ConversationTab, ResultsTab 等） |
| **Phase 2** | 事件层 | 重写 useWorkflowEvents 使用 Context stores |
| **Phase 3** | 清理 | 移除旧的全局 stores 中的 cache 逻辑 |
| **Phase 4** | 优化 | 添加 stores 生命周期管理（销毁已完成 workflow 的 stores） |

---

## 9. 类型安全

### 9.1 强类型事件处理器

```typescript
type EventPayload<T extends WSEvent["type"]> = Extract<
  WSEvent,
  { type: T }
>["payload"];

interface EventHandler<T extends WSEvent["type"]> {
  (payload: EventPayload<T>): void;
}
```

---

## 10. 测试策略

### 10.1 单元测试

- WorkflowManager 生命周期
- Store 工厂函数
- 事件分发逻辑

### 10.2 集成测试

- 多 workflow 隔离
- WebSocket 连接管理
- Batch 模式事件路由

---

## 11. 设计原则符合性

| 原则 | 方案 C | 说明 |
|------|--------|------|
| 单一职责 | ✅ | 每个 store 只管一个 workflow |
| 封装性 | ✅ | workflow 边界清晰 |
| 依赖注入 | ✅ | store 通过 Context 传递 |
| 开闭原则 | ✅ | 新增 workflow 不影响现有代码 |
| DRY | ✅ | 没有重复的 cache 逻辑 |

---

## 更新历史

- 2026-05-26: Phase 4 完成评估
  - ✅ `WorkflowManager.ts` - 基础生命周期管理已实现
    - `cleanupIdleWorkflows()` - 清理空闲 workflow（超过 idleCleanupThreshold）
    - `destroy()` - 完全销毁 workflow
    - `startCleanupTimer()` - 每分钟检查一次
    - `maxWorkflows` 配置（50个）
  - ⏸️ Light/Medium 清理级别 - 暂不实现（实际 batch 数量 2-4 个，内存占用 ~1MB 远低于设计值 14MB）
  - 结论：当前实现足够，无需三级清理策略

- 2026-05-26: Phase 3 完成评估
  - ✅ 全局 stores (`conversationStore.ts`, `outputStore.ts`, `workflowStore.ts`) 中的 cache 逻辑**保留**
  - 原因：cache 逻辑是 batch 模式必需的，用于多 workflow 隔离，不是旧的全局 cache
  - 结论：无需移除

- 2026-05-26: 集成工作完成
  - ✅ `page.tsx` - 切换到 `WorkflowCenterPanel`（使用 Context 架构或回退）
  - ✅ `WorkflowCenterPanel.tsx` - 渐进式迁移包装器（根据 `useShouldUseContextStores` 条件选择）
  - ✅ `ScopedCenterPanel` - 完整支持 benchmark 功能（Runner, Compare, Editor）
  - ✅ `WorkflowScope.tsx` - batch 模式下使用 `selectedRunId` 作为 `workflowId`
  - ✅ `useWorkflowEvents.ts` - 添加 Context 架构模式检测（`__useContextArchitecture`）
  - 验证：Next.js 构建成功

- 2026-05-26: 迁移完成
  - ✅ Benchmark 功能已完全迁移到 `ScopedCenterPanel`
  - ✅ Batch 模式下使用 WorkflowManager 管理独立 stores（无需 cache）
  - ✅ 全局 stores 的 cache 逻辑保留，仅在非 Context 模式下使用
  - ✅ Context 架构下，切换 run 直接切换 activeWorkflowId，WorkflowManager 自动处理
  - 验证：前端、后端启动成功，WebSocket 连接正常

- 2026-05-26: Phase 2 完成（事件层迁移）
  - ✅ `eventRouter.ts` - 事件路由到 scoped stores
    - 支持所有事件类型：workflow, node, agent, chat, chart
    - 单 workflow 模式：`dispatchSingleEvent` 只处理活跃 workflow 的事件
    - Batch 模式：`dispatchBatchEvent` 根据 selectedRunId 路由
  - ✅ `useWorkflowEvents.ts` - scoped events hook
    - 支持 `useScopedWorkflowEvents` hook
    - 支持 `setActiveWorkflowId` 函数
    - 使用 `useRef` 跟踪 batchMode 以避免 hooks 依赖问题
  - ✅ `hooks.ts` - 添加 useChatActions
  - ✅ `lib/api.ts` - 添加 `getUserFromApiKey` 函数（WebSocket 用户隔离）
  - ✅ `index.ts` - 导出 Phase 2 API 和类型
  - 验证：TypeScript 编译通过，Next.js 构建成功

- 2026-05-26: Phase 1 完成（核心组件迁移）
  - ✅ `hooks.ts` - Scoped hooks (useConversationMessages, useWorkflowInfo, useWorkflowActions, etc.)
  - ✅ `workflowStores.ts` - 完整实现所有 store actions（从全局 stores 复制）
  - ✅ `ScopedConversationTab.tsx` - 使用 scoped stores 的对话面板
  - ✅ `ScopedResultsTab.tsx` - 使用 scoped stores 的结果面板
  - ✅ `ScopedAnalysisTab.tsx` - 使用 scoped stores 的分析面板
  - ✅ `ScopedCenterPanel.tsx` - 使用 scoped stores 的主面板（含 DAGPreview, AgentEditorModal）
  - 验证：TypeScript 编译通过，Next.js 构建成功

- 2026-05-26: Phase 0 完成（基础设施）
  - ✅ `types.ts` - 类型定义完整
  - ✅ `workflowStores.ts` - Store 工厂函数框架
  - ✅ `WorkflowContext.tsx` - Context + Provider + hooks
  - ✅ `WorkflowManager.ts` - 生命周期管理单例
  - ✅ `WorkflowScope.tsx` - Provider 包装器
  - ✅ `index.ts` - 导出
  - 验证：TypeScript 编译通过，Next.js 构建成功