# 前端全面审查报告

> 审查日期: 2026-06-06
> 审查范围: `frontend/src/` 全部代码（132 文件，~20,104 行）
> 审查维度: 架构、状态管理、WebSocket 通信、组件质量、鲁棒性

---

## 一、执行摘要

前端代码存在 **系统性质量问题**，核心表现为：

| 维度 | 评级 | 核心问题 |
|------|------|---------|
| 架构与职责 | 🔴 差 | 1,513 行巨型文件、32 个超标文件、循环依赖 |
| 状态管理 | 🔴 差 | 历史记录无持久化、并行工作流隔离不完整 |
| WebSocket 通信 | 🟠 中 | 错误静默吞掉、事件丢失、无背压 |
| 组件质量 | 🟠 中 | 过度渲染、缺少 memo、内存泄漏风险 |
| 鲁棒性 | 🔴 差 | 空值崩溃、数据保存失败静默、无错误边界 |

**用户报告的问题根因定位：**

| 用户问题 | 根因 |
|---------|------|
| 刷新后历史记录不可见 | `runHistoryStore` 纯内存存储，无 localStorage 持久化 |
| benchmark 并行启动时 agent 输出互相干扰 | 批量模式事件路由存在竞态条件，`selectedRunId` 在事件处理期间可能变化 |
| 前端经常出问题 | 全局 try-catch 缺失、错误被静默吞掉、空值检查不足 |
| 性能差 | 组件过度渲染、流式文本无节流、大量列表无虚拟化 |

---

## 二、架构与文件职责

### 2.1 超标文件 TOP 10

| 行数 | 文件 | 职责违规 |
|------|------|---------|
| 1,513 | `workflowStores.ts` | 9 个 store 工厂 + 工具函数 + 类型定义混在一起 |
| 776 | `LlmProfileSettings.tsx` | UI 渲染 + API 调用 + 表单管理 + 全局状态同步 |
| 712 | `BenchmarkCompare.tsx` | 5 个完整标签页塞在一个文件 |
| 637 | `conversationStore.ts` | Store 包含 RAF 批处理等 UI 逻辑 |
| 499 | `routeEvent.ts` | 30+ 事件类型的路由处理全在一个 switch |
| 471 | `RunHistoryList.tsx` | 组件包含复杂的分组逻辑和 API 调用 |
| 456 | `ScopedCenterPanel.tsx` | 面板组件承担了太多子组件编排 |
| 449 | `replayEvents.ts` | 回放逻辑与事件路由耦合 |
| 426 | `hooks.ts` | 多个无关 hooks 混在一个文件 |
| 357 | `events.ts` | 所有事件类型定义在一个文件 |

### 2.2 循环依赖

```
stores/userStore.ts → import { setActiveWorkflowId } from contexts/workflow-context
contexts/workflow-context/WorkflowManager.ts → import { useUserStore } from stores/userStore
contexts/workflow-context/hooks.ts → import from stores/conversationStore
```

### 2.3 目录结构问题

- 组件目录过于扁平，缺少按功能分组
- UI 组件和业务组件混在一起
- 没有清晰的 features 分层

---

## 三、状态管理

### 3.1 历史记录消失（P0 根因）

**文件**: `stores/runHistoryStore.ts`

```typescript
// 所有状态仅内存存储，刷新即丢失
export const useRunHistoryStore = create<RunHistoryState>()((set, get) => ({
  runs: [],              // 纯内存
  selectedRunId: null,   // 纯内存
  selectedRunIds: new Set(), // 纯内存
}));
```

**对比**: `settingsStore` 已正确实现 localStorage 持久化。

### 3.2 并行工作流干扰（P0 根因）

**文件**: `contexts/workflow-context/eventRouter.ts:128-162`

```typescript
export function dispatchBatchEvent(event: WSEvent): void {
  let wid = event.payload?.workflow_id;
  if (!wid) {
    // ⚠️ 读取 selectedRunId 时，用户可能正在切换
    const { selectedRunId } = useBatchStore.getState();
    wid = selectedRunId; // 竞态：selectedRunId 可能已变化
  }
}
```

**竞态时序**:
```
T1: Workflow A 的 event 到达（无 workflow_id）
T2: 用户切换到 Workflow B → selectedRunId 变为 B
T3: event 被错误路由到 Workflow B
```

### 3.3 全局 Store 与 Scoped Store 冲突

- 旧架构的全局 `stores/conversationStore.ts` 使用模块级 `_textBuf`
- 新架构的 scoped `workflowStores.ts` 使用实例级变量
- 如果组件同时使用两者，数据不一致

### 3.4 状态清理不完整

- `resetAllStores` 只清理 scoped stores
- 全局 stores（`observabilityStore` 等）未清理
- `routeEvent.ts` 的 `_processedSeqsByWorkflow` Map 永不清理已完成 workflow

---

## 四、WebSocket 与实时通信

### 4.1 错误处理缺失

```typescript
// useWebSocket.ts:99-107
ws.onmessage = (e) => {
  try {
    const event = JSON.parse(e.data);
    onEventRef.current?.(event);
  } catch {}  // ❌ 空的 catch 块
};

// useWebSocket.ts:123-125
ws.onerror = () => {
  ws.close();  // ❌ 没有记录任何错误信息
};
```

### 4.2 事件丢失风险

- 后端 Bus 缓冲区满时直接丢弃事件（`bus.py:158-161`）
- 前端找不到 workflow entry 时静默返回（`eventRouter.ts:77-82`）
- 切换 workflow 时 seq 从 0 开始，但后端已丢弃旧事件

### 4.3 重连机制缺陷

- 无最大重试次数限制，网络永久断开时无限重连
- 重连成功后不重新订阅状态
- `lastSeqRef` 是单值，不支持多 workflow 并发
- 指数退避增长过快（默认 3s，第 4 次就 24s）

### 4.4 事件顺序无保证

- 依赖 `asyncio.Queue` 保证顺序，但 WebSocket 发送是异步的
- `agent.text_delta` 乱序会导致文本错乱
- 没有前端事件排序缓冲区

---

## 五、组件质量与性能

### 5.1 过度渲染问题

| 组件 | 问题 | 预计提升 |
|------|------|---------|
| `ChatInput.tsx` (340行) | 无条件订阅多个全局 store，即使 props 已提供 | 30-40% |
| `ConversationTab.tsx` | 无 React.memo，数组索引作 key | 25-35% |
| `RunHistoryList.tsx` (472行) | 无虚拟化，每次 runs 变化全量重分组 | 40-50% |

### 5.2 内存泄漏风险

- `routeEvent.ts` 的 `_processedSeqsByWorkflow` Map 永不清理
- `AgentMessage.tsx` 的 ToolsBadge 事件监听器可能卸载后执行
- RAF 回调在组件卸载后仍可能 setState

### 5.3 代码重复

- `ToolCallMessage.tsx` 和 `ToolCallGroup.tsx` 大量重复格式化代码
- `ResultsTab.tsx` 和 `AnalysisTab.tsx` 几乎完全相同
- 每个 store factory 有重复的实现模式

---

## 六、鲁棒性

### 6.1 崩溃路径

| 场景 | 后果 | 根因 |
|------|------|------|
| WebSocket 断线 | 无限重连、UI 卡死 | 无最大重试次数 |
| 收到 null message | 白屏 | AgentMessage 无 null 检查 |
| 图表数据格式错误 | 图表组件崩溃 | LineChartWidget 无数据验证 |
| 保存对话失败 | 数据丢失 | `.catch(() => {})` 静默吞掉 |
| 并发操作 getOrCreate | 状态不一致 | 无原子性保证 |
| JSON 解析失败 | 事件丢失 | 空 catch 块 |

### 6.2 TypeScript 类型安全

- `routeEvent.ts` 使用 `event.payload as unknown as T` 绕过检查
- 多处可选属性未用可选链处理
- 部分 `any` 类型绕过类型安全

---

## 七、修改方案

### Phase 1: 紧急修复（P0 — 2-3 天）

> 目标：修复用户直接感知的严重 bug

#### 1.1 历史记录持久化
- **文件**: `stores/runHistoryStore.ts`
- **方案**: 添加 localStorage 持久化（参考 `settingsStore` 实现）
- **工作量**: 0.5 天
- **风险**: 低 — 仅增加持久化层，不改变逻辑
- **验证**: 刷新后历史记录可见

#### 1.2 批量模式事件路由竞态修复
- **文件**: `contexts/workflow-context/eventRouter.ts`
- **方案**: 事件到达时立即快照 `selectedRunId`，使用闭包捕获而非实时读取
- **工作量**: 0.5 天
- **风险**: 低 — 缩小竞态窗口
- **验证**: 并行 benchmark 不再出现 agent 输出交叉

#### 1.3 WebSocket 错误处理
- **文件**: `hooks/useWebSocket.ts`
- **方案**:
  - 空 catch 块添加 `console.error`
  - 添加最大重试次数（默认 10 次）
  - 超过重试次数后显示连接断开提示
- **工作量**: 0.5 天
- **风险**: 低
- **验证**: 断线后日志可追踪，不再无限重连

#### 1.4 数据持久化错误通知
- **文件**: `contexts/workflow-context/eventRouter.ts`
- **方案**: `.catch(() => {})` 改为 `.catch((err) => console.error(...))`，添加重试逻辑
- **工作量**: 0.5 天
- **风险**: 低
- **验证**: 保存失败时有日志可查

### Phase 2: 架构重构（P1 — 1-2 周）

> 目标：解决职责混乱，提升可维护性

#### 2.1 拆分 `workflowStores.ts` (1,513 行)

**当前**: 1 个文件包含 9 个 store factory + 工具函数 + 类型
**目标**: 每个 store 独立文件

```
stores/workflow/
├── index.ts                 # 导出 createWorkflowStores
├── conversationStore.ts     # ~200 行
├── outputStore.ts           # ~150 行
├── workflowStore.ts         # ~150 行
├── chartStore.ts            # ~80 行
├── toolCallStore.ts         # ~100 行
├── agentIOStore.ts          # ~80 行
├── chatStore.ts             # ~80 行
├── spanStore.ts             # ~60 行
├── todoStore.ts             # ~100 行
└── utils/
    ├── counters.ts           # 计数器工厂
    └── types.ts              # 共享类型
```

- **工作量**: 2 天
- **风险**: 中 — 需要更新所有 import 路径
- **可扩展性**: 大幅提升 — 每个 store 可独立迭代
- **验证**: 所有现有测试通过 + 应用功能无回归

#### 2.2 拆分 `routeEvent.ts` (499 行)

**当前**: 一个巨型 switch 处理 30+ 事件类型
**目标**: 按事件类别分文件

```
contexts/workflow-context/routing/
├── index.ts                  # routeEvent 入口 + 去重
├── workflowEvents.ts         # workflow.started/completed/failed
├── nodeEvents.ts             # node.started/completed/failed
├── agentEvents.ts            # agent.text_delta, agent.thinking_delta
├── toolEvents.ts             # tool.* 事件
├── chatEvents.ts             # chat.question/answer
├── chartEvents.ts            # chart.render
├── todoEvents.ts             # todo.* 事件
└── utils.ts                  # payload helper + resetAllStores
```

- **工作量**: 1.5 天
- **风险**: 中
- **可扩展性**: 大幅提升 — 新事件类型只需添加新文件

#### 2.3 拆分大型组件

| 文件 | 行数 | 拆分方案 | 工作量 |
|------|------|---------|--------|
| `LlmProfileSettings.tsx` | 776 | 拆为 ProviderTab, GeneralTab, ProfileForm, useProfileApi | 1 天 |
| `BenchmarkCompare.tsx` | 712 | 拆为 ScoresTab, ChartsTab, WorkflowsTab, HistoryTab, RegressionTab | 1 天 |
| `RunHistoryList.tsx` | 472 | 拆为 RunHistoryItem, useRunGroups, 虚拟化 | 1 天 |

#### 2.4 消除循环依赖

```
stores/userStore.ts ← contexts/workflow-context
                      ↗ (循环)
contexts/workflow-context → stores/userStore.ts
```

**方案**: 提取 `setActiveWorkflowId` 到独立的 `lib/workflowNavigation.ts`，消除双向依赖。

- **工作量**: 0.5 天
- **风险**: 低

### Phase 3: 性能优化（P2 — 1 周）

> 目标：消除卡顿，提升流畅度

#### 3.1 组件渲染优化

| 优化项 | 组件 | 方案 | 预计提升 |
|--------|------|------|---------|
| React.memo | ConversationTab, ToolCallGroup | 包裹导出 | 25-35% |
| useMemo | ChatInput.streamingAgent | 缓存计算 | 30-40% |
| key 修正 | ConversationTab | 使用 message.id 替代索引 | 减少重排 |
| useCallback | RunHistoryList, Sidebar | 稳定回调引用 | 减少子组件重渲染 |

#### 3.2 虚拟化

- `RunHistoryList`: 使用 `@tanstack/react-virtual`（已安装）
- `ConversationTab`: 长对话虚拟化（已有 `@tanstack/react-virtual` 依赖）
- 图表列表: ResultsTab/AnalysisTab 分页加载

#### 3.3 流式文本优化

- RAF 批处理添加 cleanup 标志（防卸载后 setState）
- 考虑 `requestIdleCallback` 替代部分 RAF
- 限制单次更新最大文本长度

### Phase 4: 鲁棒性加固（P3 — 1 周）

> 目标：消除所有静默失败，实现生产级错误处理

#### 4.1 全局错误边界增强

```typescript
// ErrorBoundary.tsx 升级
- 错误日志上报
- 错误详情展示（开发模式）
- 分模块错误边界（Conversation、DAG、Settings 独立）
```

#### 4.2 事件处理 try-catch

```typescript
// eventRouter.ts — 每个 store 操作包裹 try-catch
function routeEventToStores(event: WSEvent): void {
  try {
    const stores = manager.getStores(wid);
    routeEvent(stores, event, buildLiveContext(stores));
  } catch (err) {
    console.error(`[EventRouter] Error routing event ${event.type}:`, err);
    // 不中断事件处理链
  }
}
```

#### 4.3 数据验证

- 所有 WebSocket 事件入口添加 schema 验证（zod）
- 图表组件添加 data null check
- AgentMessage 添加 null/undefined guard

#### 4.4 内存管理

```typescript
// routeEvent.ts — 定期清理已完成 workflow 的 seq tracker
// workflow.completed/failed/cancelled 时:
_processedSeqsByWorkflow.delete(wid);

// WorkflowManager — 添加 GC 机制
cleanupStale(maxAgeMs: number): void {
  // 清理超过 maxAgeMs 未活跃的 workflow entry
}
```

---

## 八、方案评估矩阵

| Phase | 工作量 | 风险 | 用户价值 | 可扩展性收益 | 优先级 |
|-------|--------|------|---------|-------------|--------|
| Phase 1 | 2-3 天 | 低 | 🔴 极高 — 修用户直接感知的 bug | 低 | **P0** |
| Phase 2 | 1-2 周 | 中 | 🟠 高 — 大幅提升可维护性 | 🔴 极高 | **P1** |
| Phase 3 | 1 周 | 低 | 🟠 高 — 消除卡顿 | 中 | **P2** |
| Phase 4 | 1 周 | 低 | 🟡 中 — 长期稳定性 | 🟠 高 | **P3** |

**总工作量估算**: 4-6 周（可与功能开发交替进行）

---

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Phase 2 重构引入新 bug | 回归 | 每个 store 拆分后立即运行测试 + 手动验证 |
| 循环依赖修复影响多个文件 | 编译失败 | 逐步迁移，每步验证编译通过 |
| 持久化导致 localStorage 满 | 数据丢失 | 限制存储条数 + LRU 淘汰 |
| 事件路由修改影响实时体验 | 消息丢失 | 先加日志观察，再改逻辑 |
| 虚拟化导致滚动体验变化 | 用户体验 | 逐步引入，对比测试 |

---

## 十、实施建议

1. **立即启动 Phase 1** — 这些是用户每天遇到的 bug，修复成本低收益高
2. **Phase 2 按文件逐步拆分** — 不要一次性重构，每拆一个文件就验证
3. **Phase 3 与 Phase 2 交替进行** — 拆分文件时顺便做 memo 优化
4. **Phase 4 作为持续改进** — 每次改代码时顺便加强错误处理

---

## 十一、Phase 1 实施记录

> 实施日期: 2026-06-06
> 分支: feat/unified-event-architecture
> 状态: 已完成，通过 code review

### 改动文件清单

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `frontend/src/lib/createPersistedStore.ts` | 新建 | +120 |
| `frontend/src/stores/runHistoryStore.ts` | 重写 | +83/-65 |
| `frontend/src/contexts/workflow-context/eventRouter.ts` | 重构 | +100/-72 |
| `frontend/src/hooks/useWebSocket.ts` | 重构 | +77/-46 |
| `frontend/src/components/ErrorBoundary.tsx` | 增强 | +48/-14 |
| `frontend/src/components/layout/ScopedCenterPanel.tsx` | 增强 | +15 |
| `frontend/src/contexts/workflow-context/routeEvent.ts` | 增强 | +10 |
| `frontend/src/contexts/workflow-context/WorkflowManager.ts` | 增强 | +4 |

### 架构决策记录

| 决策 | 原因 |
|------|------|
| 持久化用独立 vanilla store 而非 zustand middleware | 避免 setState monkey-patch 的 TS 类型问题；读写分离，零读取开销 |
| selectedRunId 在 dispatchBatchEvent 顶部一次快照 | 消除用户快速切换导致的竞态；两个值在闭包中冻结 |
| WebSocket 用布尔 isConnected 而非完整状态机 | 当前 UI 只需要 connected/disconnected；完整状态机留给后续 Phase |
| ErrorBoundary 不实现 isolate prop | React 错误边界默认已隔离（子 boundary 捕获的错误不传播到父） |

### Code Review 发现与修复

| 级别 | 问题 | 修复 |
|------|------|------|
| Critical | `dispatchBatchEvent` 中 `selectedRunId` 单独读取，与冻结的 wid 分离 | 将 selectedRunId 移至函数顶部，与 wid 一起快照 |
| Important | `isolate` prop 声明但未实现 | 移除未使用的 prop |
| Important | `maxSize` 注释说"字节"但实际是字符 | 更正文档为 UTF-16 code units |
| Important | 浅合并的 hydrate 对嵌套对象有风险 | 添加 JSDoc 警告，说明仅适用于扁平状态 |

### 验证结果

- `npm run build` ✅ 编译通过，0 错误
- `pytest` ✅ 385 passed, 0 regression
- 2 个 pre-existing failures 与本次改动无关（test_cancel_preserves_events, test_chart payload）

### 待办（后续 Phase）

- **E2E 测试**: 真实 LLM 并行 workflow 隔离验证（Phase 1 Step 7，需启动 server）
- **createPersistedStore 改进**: 脏标记避免无效写入、测试重置方法（I-3, I-5）
- **ConnectionState 状态机**: 完整的 WS 连接状态暴露给 UI（S-5）

关键原则：**每个 Phase 独立可交付，不依赖后续 Phase。**
