# Current Task

**当前任务**: 修复前端数据流三大缺陷（实时对话、Chart渲染、Collapsible交互）
**状态**: in_progress
**优先级**: P0 — 最高优先级，阻塞所有其他工作

---

## 问题描述

运行 workflow 后存在三个前端缺陷：

1. **实时对话不可见**：workflow 启动后运行过程中，Conversation 标签页无流式输出，看不到 agent 文字和工具调用
2. **Charts 不显示**：workflow 完成后 Results 标签页为空，图表不渲染
3. **Collapsible 不可交互**：点击图表组标题行无法收起/展开

## 已完成的诊断和改动

详见 `docs/status/2026-05-27-frontend-data-flow-issues.md`

### 后端改动（已验证正确）
- `harness/run_store.py` — 新增 `events` 字段持久化
- `server/runner.py` — 用 `ConversationCollector` 替代 `build_conversation()` 修复消息排序
- `harness/extensions/bus.py` — buffer 从 500 增大到 2000
- 后端测试全部通过（215/215）

### 前端改动（仍有问题）
- `contexts/workflow-context/replayEvents.ts` — 新建事件回放工具
- `stores/viewStore.ts` — showReplay 时回放事件到 scoped stores
- `components/layout/WorkflowCenterPanel.tsx` — 统一 live/replay 走 scoped 架构
- `components/layout/ScopedCenterPanel.tsx` — 移除 isReplay 组件分支
- `components/results/ResultsTab.tsx` 等 4 文件 — Collapsible 用 localCollapsed
- `contexts/workflow-context/useWorkflowWS.ts` — onEvent 用 workflowId 替代全局 store

### 仍存在的问题
- 从 landing page 启动 workflow 后，事件流没有到达 scoped stores
- 根因疑似：CenterPanel(legacy) → WorkflowScope(scoped) 的渲染切换时序中，
  WebSocket 连接和 store 创建之间存在断裂
- 需要在浏览器 DevTools 中实际调试事件流，不能用猜测驱动开发

## 必读文件

1. `docs/status/2026-05-27-frontend-data-flow-issues.md` — 完整诊断文档
2. `docs/plans/2026-05-27-unified-event-stream-architecture.md` — 架构改进计划
3. `frontend/src/contexts/workflow-context/useWorkflowWS.ts` — 事件路由入口
4. `frontend/src/contexts/workflow-context/eventRouter.ts` — 事件到 store 的路由
5. `frontend/src/components/layout/WorkflowCenterPanel.tsx` — live/replay 渲染决策
