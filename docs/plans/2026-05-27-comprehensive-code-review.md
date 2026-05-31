# 全面代码审查计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 对前端+后端所有功能点进行系统性代码审查，确保每个功能完全符合预期、所有功能正常工作。

**Architecture:** 按功能域分层审查——前端 UI 组件、前端状态管理+事件路由、后端 REST API、后端 WebSocket、核心引擎、扩展系统。每个 Task 覆盖一个独立功能点，验证代码正确性 + 运行测试 + 手动检查。

**Tech Stack:** React/Next.js 14, Zustand, ReactFlow, FastAPI, WebSocket, LangGraph, Pydantic AI

---

## 审查范围总览

| 阶段 | 覆盖范围 | Task 数 |
|------|---------|---------|
| A. 前端 UI 组件 | 所有页面、组件、交互 | 8 |
| B. 前端状态+事件 | Stores、WebSocket hooks、事件路由 | 6 |
| C. 后端 REST API | 所有端点、权限、数据 | 7 |
| D. 后端 WebSocket | 连接、事件过滤、批量模式 | 3 |
| E. 核心引擎 | DAG 编译、Agent 执行、状态 | 4 |
| F. 扩展系统 | Eval、Compact、Plugins、Bus | 3 |
| G. 当前分支变更 | Context Architecture WS 生命周期 | 3 |
| **总计** | | **34** |

---

## Phase A: 前端 UI 组件审查

### Task A1: Landing Page — 工作流模板选择

**Files:**
- Review: `frontend/src/components/layout/ScopedCenterPanel.tsx:353-408` (landing page UI)
- Review: `frontend/src/components/output/WorkflowLauncher.tsx` (legacy launcher)
- Review: `frontend/src/components/chat/ChatInput.tsx:94-106` (startWorkflow 路径)

**审查要点：**
1. 模板列表从 `/api/workflows/definitions` 正确加载
2. 模板选中/取消选中逻辑正确（toggle behavior）
3. `startWorkflow` 构造正确的 POST body（name, workflow, agents, inputs）
4. 模板卡片显示正确的 agent 数量和名称
5. 错误处理：API 失败时静默失败（catch → {}）

**Step 1: 读代码确认模板加载逻辑**

检查 `ScopedCenterPanel.tsx:162-167` 的 `useEffect` 是否正确获取并设置 templates。

**Step 2: 读代码确认 startWorkflow 构造**

检查 `ScopedCenterPanel.tsx:197-229` 的 `startWorkflow` 是否正确映射 agents 字段。

**Step 3: 检查模板卡片渲染**

确认 `ScopedCenterPanel.tsx:365-397` 的模板网格渲染：每个卡片显示名称和 agent 数量。

**Step 4: 验证 ChatInput 在 idle 状态的 startWorkflow 传递**

检查 `ScopedCenterPanel.tsx:399-405` 和 `ScopedCenterPanel.tsx:501-507` 是否正确传递 `startWorkflow`（idle 时传，运行时不传）。

**Step 5: 检查 fetch 是否使用认证**

确认 `ScopedCenterPanel.tsx` 中的 `fetch("/api/workflows/definitions")` 缺少 `fetchWithAuth` —— 这是一个 bug。

**Expected:** 模板选择和启动流程完整可用。若发现未使用 `fetchWithAuth`，标记为 bug。

---

### Task A2: Conversation Tab — 消息渲染

**Files:**
- Review: `frontend/src/components/conversation/ConversationTab.tsx`
- Review: `frontend/src/components/conversation/ScopedConversationTab.tsx`
- Review: `frontend/src/components/conversation/AgentMessage.tsx`
- Review: `frontend/src/components/conversation/UserMessage.tsx`
- Review: `frontend/src/components/conversation/SystemMessage.tsx`
- Review: `frontend/src/components/conversation/ToolCallMessage.tsx`
- Review: `frontend/src/components/conversation/ToolCallGroup.tsx`

**审查要点：**
1. 消息类型正确区分：agent, user, system, tool_call
2. Agent 消息：streaming 状态显示光标，done 状态显示内容，error 显示错误
3. Agent 消息折叠/展开逻辑正确
4. IO 面板（In/Out 按钮）正确显示 input/system/output
5. Token 用量正确显示
6. Tool badge 正确显示工具列表
7. 自动滚动到最新消息
8. 工具调用分组正确（连续 tool_call 消息归为一组）

**Step 1: 读 ConversationTab 确认消息分组逻辑**

检查 `ConversationTab.tsx` 中的消息遍历和 ToolCallGroup 分组算法。

**Step 2: 读 ScopedConversationTab 确认 Context 架构集成**

确认 Scoped 版本正确使用 `useConversationMessages()` 和 scoped stores。

**Step 3: 读 AgentMessage 确认所有状态渲染**

检查四种状态：streaming（光标+文本），done（完整文本），error（错误信息），interrupted（折叠）。

**Step 4: 确认 IO Sheet 数据来源**

检查 `AgentMessage.tsx:134-137` 的 agentIO 和 nodeState 读取优先级（scoped > global）。

**Step 5: 验证 Markdown 渲染**

确认 `MarkdownText` 组件正确处理代码块、表格、链接等。

**Expected:** 所有消息类型正确渲染，IO 面板数据准确。

---

### Task A3: Chat Input — 问答/停止/恢复

**Files:**
- Review: `frontend/src/components/chat/ChatInput.tsx` (完整文件)
- Review: `frontend/src/components/chat/ChatMessage.tsx`

**审查要点：**
1. 正常输入 → startWorkflow 或 sendAnswer
2. Chat 问答：pendingQuestion 时自动聚焦，发送答案
3. Stop & Regenerate：找到 streaming agent，发送 stop 信号，调用 cancel API
4. Paused 状态：输入 guidance → sendStopAndRegenerate → resume API
5. Scoped store 注入正确（propPendingId vs globalPendingId 优先级）
6. 键盘事件：Enter 提交、Shift+Enter 换行
7. `fetchWithAuth` 使用一致性

**Step 1: 读 ChatInput 确认 scoped store 注入**

检查 `ChatInput.tsx:33-60` 的 prop 优先级逻辑（prop !== undefined → prop : global）。

**Step 2: 确认 handleSubmit 三条路径**

检查 `ChatInput.tsx:83-104`：hasPendingQuestion → sendAnswer, canStartWorkflow → startWorkflow, else → no-op。

**Step 3: 确认 handleStop 流程**

检查 `ChatInput.tsx:106-126`：获取 streamingAgent → interrupt → sendStopAndRegenerate → cancel API。

**Step 4: 确认 handlePausedSubmit 流程**

检查 `ChatInput.tsx:130-152`：guidance → sendStopAndRegenerate → resume API。

**Step 5: 检查 cancel/resume fetch 是否使用 fetchWithAuth**

**Expected:** 三种交互模式（正常输入、问答、停止/恢复）全部正确。

---

### Task A4: DAG 预览与节点编辑

**Files:**
- Review: `frontend/src/components/dag/DAGPreview.tsx`
- Review: `frontend/src/components/dag/DAGPreviewNode.tsx`
- Review: `frontend/src/components/dag/DAGStatusBar.tsx`
- Review: `frontend/src/components/agent/AgentEditorModal.tsx`
- Review: `frontend/src/components/agent/AgentDiffModal.tsx`

**审查要点：**
1. Dagre 自动布局正确
2. 条件边（on_pass/on_fail）标签和样式
3. 节点点击 → AgentEditorModal
4. Agent 编辑 PUT API 调用正确
5. Diff modal 正确对比 live vs saved 版本
6. Mini-map 仅在 >5 节点时显示

**Step 1: 读 DAGPreview 确认布局和交互**

**Step 2: 读 AgentEditorModal 确认保存逻辑**

**Step 3: 读 AgentDiffModal 确认对比逻辑**

**Expected:** DAG 渲染正确，编辑和 diff 功能正常。

---

### Task A5: Results/Analysis Tabs — 图表渲染

**Files:**
- Review: `frontend/src/components/results/ResultsTab.tsx`
- Review: `frontend/src/components/results/ScopedResultsTab.tsx`
- Review: `frontend/src/components/analysis/AnalysisTab.tsx`
- Review: `frontend/src/components/analysis/ScopedAnalysisTab.tsx`
- Review: `frontend/src/components/output/ChartGroup.tsx`
- Review: `frontend/src/components/output/ChartGroupCollection.tsx`
- Review: `frontend/src/components/output/charts/*.tsx` (11 chart types)

**审查要点：**
1. chart_groups 正确按 category 过滤（null → Results, "analysis" → Analysis）
2. 折叠/展开分组
3. 11 种图表类型全部有对应渲染器
4. Replay 模式从 run.chart_groups 读取
5. Live 模式从 scoped/global chartStore 读取

**Step 1: 读 filterGroupsByCategory 逻辑**

检查 `chartStore.ts` 中的过滤逻辑。

**Step 2: 确认 Scoped 版本正确读取 chart store**

**Step 3: 抽查 3 种图表组件（LineChart, BarChart, DataTable）**

**Expected:** 所有图表类型正确渲染，分组和过滤准确。

---

### Task A6: Sidebar — 运行历史、Agent 浏览、Benchmark

**Files:**
- Review: `frontend/src/components/sidebar/Sidebar.tsx`
- Review: `frontend/src/components/sidebar/RunHistoryList.tsx`
- Review: `frontend/src/components/sidebar/AgentBrowser.tsx`
- Review: `frontend/src/components/sidebar/TemplateLibrary.tsx`

**审查要点：**
1. 运行列表按 workflow_name 分组
2. 状态图标正确（running=spinner, completed=check, failed=x, paused=pause）
3. 操作按钮：Pause/Resume/Rerun/Delete 权限正确
4. Agent 浏览器显示 DAG agents 或 replay snapshot
5. Benchmark 列表和选择

**Step 1: 读 RunHistoryList 确认分组和操作**

**Step 2: 读 AgentBrowser 确认 agent 列表来源**

**Step 3: 检查操作按钮的 API 调用是否使用 fetchWithAuth**

**Expected:** 侧边栏功能完整，操作按钮权限正确。

---

### Task A7: Benchmark 功能 — Runner/Editor/Compare

**Files:**
- Review: `frontend/src/components/benchmark/BenchmarkRunner.tsx`
- Review: `frontend/src/components/benchmark/BenchmarkEditor.tsx`
- Review: `frontend/src/components/benchmark/BenchmarkCompare.tsx`

**审查要点：**
1. Runner：选择 workflow → 运行 → 进度跟踪 → 选择 run 查看
2. Editor：创建/编辑 benchmark（name, tasks, description）
3. Compare：多 run 对比结果
4. Batch WebSocket 连接正确
5. fetchWithAuth 使用

**Step 1: 读 BenchmarkRunner 确认运行流程**

**Step 2: 读 BenchmarkEditor 确认保存/更新逻辑**

**Step 3: 读 BenchmarkCompare 确认对比数据来源**

**Expected:** Benchmark 三个子功能全部正确。

---

### Task A8: Diagnostics — Trace/Tools/Errors 面板

**Files:**
- Review: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`
- Review: `frontend/src/components/diagnostics/TraceTab.tsx`
- Review: `frontend/src/components/diagnostics/ToolCallsTab.tsx`
- Review: `frontend/src/components/diagnostics/ErrorsTab.tsx`

**审查要点：**
1. 三个 Tab 正确切换
2. Live 模式从 stores 读取
3. Replay 模式从 run record 派生
4. Trace 显示每个节点的执行时间和 token 用量
5. Tool calls 显示完整调用链
6. Errors 仅显示 failed 节点

**Step 1: 读 DiagnosticsPanel 确认 Tab 切换**

**Step 2: 读 TraceTab 确认数据来源**

**Step 3: 确认 Replay 模式数据派生逻辑**

**Expected:** 诊断面板在 live 和 replay 模式下均正确。

---

## Phase B: 前端状态管理与事件路由

### Task B1: Zustand Stores 数据完整性

**Files:**
- Review: `frontend/src/stores/workflowStore.ts`
- Review: `frontend/src/stores/conversationStore.ts`
- Review: `frontend/src/stores/outputStore.ts`
- Review: `frontend/src/stores/chartStore.ts`
- Review: `frontend/src/stores/chatStore.ts`
- Review: `frontend/src/stores/toolCallStore.ts`
- Review: `frontend/src/stores/agentIOStore.ts`
- Review: `frontend/src/stores/batchStore.ts`
- Review: `frontend/src/stores/viewStore.ts`
- Review: `frontend/src/stores/runHistoryStore.ts`
- Review: `frontend/src/stores/userStore.ts`

**审查要点：**
1. 每个 store 的 state shape 正确
2. Actions 无副作用泄漏
3. Cache 机制（batch mode）正确保存/恢复
4. Reset 函数清理所有状态
5. `conversationStore` 的消息生命周期：addAgentMessage → appendAgentText → completeAgentMessage

**Step 1: 抽查 workflowStore 的事件处理器**

确认 `handleWorkflowStarted`, `handleNodeStarted`, `handleNodeCompleted`, `handleNodeFailed` 正确更新状态。

**Step 2: 抽查 conversationStore 的消息生命周期**

确认 `addAgentMessage` → `appendAgentText` → `completeAgentMessage` 流程无竞态。

**Step 3: 抽查 cache 保存/恢复逻辑**

确认 `saveToCache`/`restoreFromCache` 在 batch 切换时正确工作。

**Step 4: 检查 toolCallStore 的 ID 计数器**

确认 `nextToolCallId` 不会重复。

**Expected:** 所有 store 状态管理正确，无竞态条件。

---

### Task B2: Legacy 事件路由（useWorkflowEvents）

**Files:**
- Review: `frontend/src/hooks/useWorkflowEvents.ts` (完整文件, 511 行)

**审查要点：**
1. `_routeToUIStores` 处理所有 16 种事件类型
2. `node.completed` 的 output_result 正确填充 conversation
3. Batch mode cache 更新逻辑
4. `_restoreConversation` 从后端恢复
5. `setActiveWorkflowId` 切换时正确保存/恢复

**Step 1: 逐一检查 switch case 覆盖**

确认 16 种事件类型全部处理：workflow.started/completed/error/cancelled/resumed, node.started/completed/failed, agent.text_delta/tool_call/tool_result/tool_output_delta, chat.question, chart.render。

**Step 2: 检查 node.completed 的 output_result 填充**

确认 `useWorkflowEvents.ts:194-246` 的 fallback 逻辑（无 streaming 消息时创建 placeholder）。

**Step 3: 检查 dispatchBatchEvent 的路由逻辑**

确认 `_isSelectedRun` 过滤 + lifecycle 事件更新 batchStore。

**Expected:** 所有事件类型正确路由到对应的 store。

---

### Task B3: Context 架构事件路由（eventRouter.ts）

**Files:**
- Review: `frontend/src/contexts/workflow-context/eventRouter.ts` (完整文件)

**审查要点：**
1. `routeEventToStores` 使用 scoped stores 而非 global stores
2. `dispatchSingleEvent` 正确过滤 workflow_id
3. `dispatchBatchEvent` 正确处理 batch lifecycle
4. `saveConversation`/`saveCharts` 使用 scoped store 数据
5. 与 legacy `_routeToUIStores` 的逻辑一致性

**Step 1: 对比 eventRouter.ts 和 useWorkflowEvents.ts 的事件处理**

确认两个路由的每个事件处理逻辑一致。

**Step 2: 检查 scoped stores 获取方式**

确认 `manager.getStores(wid)` 返回的 stores 正确用于事件分发。

**Step 3: 确认 saveConversation/saveCharts 使用认证**

检查 `eventRouter.ts:85-89` 和 `eventRouter.ts:95-105` 是否使用 `fetchWithAuth`。

**Expected:** Context 架构事件路由与 legacy 路由逻辑一致。

---

### Task B4: WebSocket Hooks

**Files:**
- Review: `frontend/src/hooks/useWebSocket.ts`
- Review: `frontend/src/hooks/useBatchWebSocket.ts`
- Review: `frontend/src/contexts/workflow-context/useWorkflowWS.ts`

**审查要点：**
1. 连接/断开生命周期正确
2. 自动重连（指数退避，最大 30s）
3. 用户隔离（query param user_id）
4. 消息序列化/反序列化
5. cleanup 函数正确关闭连接

**Step 1: 读 useWebSocket 确认连接管理**

**Step 2: 读 useBatchWebSocket 确认 batch endpoint**

**Step 3: 读 useWorkflowWS 确认 Context 架构的 WS 管理**

**Expected:** WebSocket 连接管理健壮，重连和用户隔离正确。

---

### Task B5: WorkflowManager — 生命周期管理

**Files:**
- Review: `frontend/src/contexts/workflow-context/WorkflowManager.ts`
- Review: `frontend/src/contexts/workflow-context/types.ts`

**审查要点：**
1. Singleton 模式正确
2. `getOrCreate` 创建独立 stores
3. `setActiveWorkflowId` 正确管理 lifecycle 状态
4. `destroy` 正确清理资源
5. 空闲清理定时器（5min threshold, max 50）
6. `dispatchEvent` TODO 注释 — 未实现的事件分发

**Step 1: 读 WorkflowManager 确认生命周期**

**Step 2: 确认 destroy 清理 WS 连接**

**Step 3: 标记 dispatchEvent 的 TODO 为已知问题**

**Expected:** 生命周期管理正确，已知 TODO 不影响当前功能。

---

### Task B6: WorkflowStores 工厂

**Files:**
- Review: `frontend/src/contexts/workflow-context/workflowStores.ts`
- Review: `frontend/src/contexts/workflow-context/WorkflowContext.tsx`
- Review: `frontend/src/contexts/workflow-context/hooks.ts`
- Review: `frontend/src/contexts/workflow-context/index.ts`

**审查要点：**
1. `createWorkflowStores` 创建所有必要 stores
2. 每个 store 的创建函数独立
3. React context 和 hooks 正确暴露 store 访问
4. `useWorkflowStore`, `useConversationStores` 等 hooks 返回正确的数据

**Step 1: 读 workflowStores.ts 确认所有 store 创建**

**Step 2: 读 hooks.ts 确认 hook 实现**

**Step 3: 读 index.ts 确认导出完整性**

**Expected:** Store 工厂和 hooks 正确提供 per-workflow 隔离的 stores。

---

## Phase C: 后端 REST API

### Task C1: 用户认证与权限

**Files:**
- Review: `server/routes.py:1-110` (user management endpoints)
- Review: `server/app.py:59-125` (middleware, no auth middleware)
- Review: `harness/user_manager.py`

**审查要点：**
1. `GET /api/me` 正确从 X-API-Key 或 X-User-Id 解析用户
2. `POST /api/users` admin 检查是否存在
3. `DELETE /api/users/{user_id}` admin 检查
4. 无效 key 降级到 default 用户
5. 无全局 auth middleware — 每个 endpoint 自行检查

**Step 1: 读 /api/me 实现**

**Step 2: 检查 admin check 在 POST/DELETE users 中**

**Step 3: 确认 fallback 用户逻辑**

**Expected:** 认证逻辑正确，已知限制（无热更新、invalid key fallback）记录。

---

### Task C2: Workflow CRUD + 执行

**Files:**
- Review: `server/routes.py:788-814` (POST /api/workflows)
- Review: `server/routes.py:1158-1170` (GET /api/workflows/{id})
- Review: `server/routes.py:1173-1201` (POST cancel)
- Review: `server/routes.py:1204-1211` (GET dag)
- Review: `server/routes.py:1214-1230` (GET trace)
- Review: `server/routes.py:407-412` (GET definitions)
- Review: `server/routes.py:415-449` (DELETE definitions)

**审查要点：**
1. 并发限制（max_concurrent=50）
2. cancel 权限检查（owner or admin）
3. DAG 结构缓存
4. definitions 用户隔离（shared + private）
5. DELETE definitions 权限（admin 删 shared，user 删 own）

**Step 1: 检查并发限制实现**

**Step 2: 检查 cancel 权限**

**Step 3: 检查 definitions 用户隔离**

**Expected:** Workflow 端点权限和并发控制正确。

---

### Task C3: Run 管理

**Files:**
- Review: `server/routes.py:486-538` (GET /api/runs)
- Review: `server/routes.py:541-595` (GET /api/runs/{id})
- Review: `server/routes.py:452-483` (DELETE run)
- Review: `server/routes.py:598-634` (PATCH conversation)
- Review: `server/routes.py:637-662` (PATCH charts)
- Review: `server/routes.py:1233-1332` (resume)
- Review: `server/routes.py:1335-1437` (rerun)

**审查要点：**
1. Run listing 用户隔离（admin see all）
2. Run detail 权限检查（owner or admin）
3. DELETE/PATCH 权限检查
4. resume/rerun 权限检查（当前分支修复）
5. rerun 正确重建 agents snapshot

**Step 1: 检查所有权限检查**

**Step 2: 检查 rerun 的 agents 重建**

**Step 3: 检查 run listing 过滤逻辑**

**Expected:** 所有 run 操作权限正确。

---

### Task C4: Agent 管理

**Files:**
- Review: `server/routes.py:196-346` (GET/PUT agents)

**审查要点：**
1. Agent 查找规则（private → shared → 404）
2. PUT agent 验证（先 parse 再写入）
3. target 参数（private vs shared）
4. MD 内容正确写入

**Step 1: 读 GET /api/agents 和 GET /api/agents/{name}**

**Step 2: 读 PUT /api/agents/{name}/md**

**Step 3: 确认 resolve_agent_md 优先级**

**Expected:** Agent CRUD 正确，文件写入安全。

---

### Task C5: Batch + Benchmark API

**Files:**
- Review: `server/routes.py:817-907` (batch endpoints)
- Review: `server/routes.py:921-1071` (benchmark CRUD + run)
- Review: `server/batch_fan_in.py`

**审查要点：**
1. Batch 创建正确隔离每个 run 的 Bus
2. Batch status 查询
3. Benchmark CRUD 完整
4. Benchmark run 创建 batch
5. Benchmark results 聚合分数
6. 无用户隔离（已知限制）

**Step 1: 读 batch 创建逻辑**

**Step 2: 读 benchmark run 流程**

**Step 3: 读 score 聚合逻辑**

**Expected:** Batch 和 Benchmark API 功能正确。

---

### Task C6: Config + Tools + Charts + Health

**Files:**
- Review: `server/routes.py:168-193` (config)
- Review: `server/routes.py:349-404` (tools, charts)
- Review: `server/routes.py:168-171` (health)

**审查要点：**
1. Config set/get（key masked）
2. Tools 列表
3. Chart HTTP fallback（POST /api/charts）
4. Health check

**Step 1: 确认 config key masking**

**Step 2: 确认 chart event 路由**

**Expected:** Config、Tools、Charts 端点正确。

---

### Task C7: 运行后端测试套件

**Files:**
- Test: `tests/server/test_routes.py`
- Test: `tests/server/test_ws_handler.py`
- Test: `tests/server/test_event_bus.py`

**Step 1: 运行后端测试**

```bash
pytest tests/server/ -v --timeout=30
```

**Step 2: 运行 harness 核心测试**

```bash
pytest tests/harness/ tests/engine/ tests/test_api.py tests/test_integration.py -v --timeout=30
```

**Step 3: 记录失败用例并分析**

**Expected:** 所有测试通过。如有失败，记录原因。

---

## Phase D: 后端 WebSocket

### Task D1: Workflow WebSocket — 事件过滤

**Files:**
- Review: `server/ws_handler.py:1-230` (完整文件)

**审查要点：**
1. BROADCAST_RULES 正确定义（self/all/admin）
2. `_forward_events_filtered` 检查 event_user_id == ws_user_id
3. 消息类型处理：chat.answer, agent.stop_and_regenerate
4. 用户 ID 从 query param 或 header 获取
5. fallback 到 anonymous UUID

**Step 1: 读 BROADCAST_RULES 定义**

**Step 2: 读 _forward_events_filtered**

**Step 3: 读消息处理逻辑**

**Expected:** WebSocket 事件正确过滤和转发。

---

### Task D2: Batch WebSocket

**Files:**
- Review: `server/ws_handler.py:282-340` (batch endpoint)

**审查要点：**
1. BatchFanIn 正确合并多个 run 的事件
2. Per-run 用户过滤
3. batch.completed 合成事件
4. Cleanup 正确

**Step 1: 读 batch WebSocket endpoint**

**Step 2: 检查 BatchFanIn 集成**

**Expected:** Batch WebSocket 正确聚合多 run 事件。

---

### Task D3: Runner — 工作流执行管理

**Files:**
- Review: `server/runner.py` (完整文件, 419 行)

**审查要点：**
1. 并发控制（semaphore）
2. Cancel 逻辑（2s 超时等待）
3. work_dir 安全验证（拒绝 /etc, /proc 等）
4. 错误处理和 cleanup
5. MCP 服务器生命周期
6. Run 持久化（conversation + charts）

**Step 1: 读 submit 和 _run_workflow**

**Step 2: 检查 cancel 逻辑**

**Step 3: 检查 cleanup 逻辑（cwd restore, MCP disconnect）**

**Expected:** Runner 正确管理工作流执行和资源。

---

## Phase E: 核心引擎

### Task E1: DAG 编译 — Topological Sort + Cycle Detection

**Files:**
- Review: `harness/compiler/dag_builder.py`
- Review: `harness/compiler/md_parser.py`

**审查要点：**
1. 拓扑排序正确
2. 循环检测
3. 缺失依赖检测
4. 条件边（on_pass/on_fail）排除在循环检测之外

**Step 1: 读 build_dag 算法**

**Step 2: 运行编译器测试**

```bash
pytest tests/test_resolve_agent_md.py tests/test_md_parser_eval.py -v
```

**Expected:** DAG 编译正确处理所有边界情况。

---

### Task E2: Macro Graph — LangGraph StateGraph 构建

**Files:**
- Review: `harness/engine/macro_graph.py` (完整文件)

**审查要点：**
1. StateGraph 正确构建
2. 条件边（on_pass/on_fail）正确路由
3. Passthrough 节点（fan-out）
4. Eval judge 节点
5. Stop-and-regenerate 逻辑
6. Checkpoint 支持

**Step 1: 读 build 方法**

**Step 2: 读 _make_node_func 和 _make_judge_node_func**

**Step 3: 运行测试**

```bash
pytest tests/engine/test_macro_graph.py tests/engine/test_macograph_events.py -v
```

**Expected:** Graph 构建和执行逻辑正确。

---

### Task E3: Micro Agent — Pydantic AI Agent 创建

**Files:**
- Review: `harness/engine/micro_agent.py`
- Review: `harness/engine/llm.py`
- Review: `harness/engine/llm_executor.py`
- Review: `harness/engine/state.py`

**审查要点：**
1. Agent prompt 构造（system + inputs + upstream）
2. Tool 解析和注册
3. Streaming 执行
4. Interrupt 检查
5. Token 使用追踪

**Step 1: 读 build_node_prompt**

**Step 2: 读 LLMExecutor.run**

**Step 3: 运行测试**

```bash
pytest tests/engine/test_micro_agent.py tests/engine/test_llm_executor.py -v
```

**Expected:** Agent 创建和执行流程正确。

---

### Task E4: API 公共接口

**Files:**
- Review: `harness/api.py`

**审查要点：**
1. Agent 定义接口
2. Workflow 定义和编译
3. run/arun 同步/异步执行
4. save/load 持久化
5. list_saved 工作流查询

**Step 1: 读 Workflow 类主要方法**

**Step 2: 运行 API 测试**

```bash
pytest tests/test_api.py tests/test_api_list_saved.py -v
```

**Expected:** 公共 API 接口正确。

---

## Phase F: 扩展系统

### Task F1: EventBus (Bus) — 事件分发 + 扩展调度

**Files:**
- Review: `harness/extensions/bus.py`

**审查要点：**
1. WS 客户端订阅/取消
2. Hook 并发执行（fire-and-forget）
3. Middleware 链式执行
4. 用户上下文（with_user_context）
5. Ring buffer for replay

**Step 1: 读 Bus 核心方法**

**Step 2: 运行测试**

```bash
pytest tests/harness/extensions/test_bus.py -v
```

**Expected:** Bus 正确处理事件分发和扩展调度。

---

### Task F2: Eval Judge — 自动评审

**Files:**
- Review: `harness/extensions/eval/decisions.py`
- Review: `harness/extensions/eval/judge.py`
- Review: `harness/extensions/eval/summarizer.py`

**审查要点：**
1. GraphMutator 正确插入 judge 节点
2. 条件边路由（on_pass/on_fail）
3. Judge prompt 构造
4. Score 提取

**Step 1: 读 EvalJudge.mutate**

**Step 2: 运行测试**

```bash
pytest tests/harness/extensions/eval/ -v
```

**Expected:** Eval 系统正确插入和执行评审。

---

### Task F3: Collectors — 对话和图表持久化

**Files:**
- Review: `harness/extensions/collectors.py` (新增文件，当前分支)

**审查要点：**
1. `ConversationCollector` 从 agent_io 构建对话
2. `ChartCollector` 从 chart.render 构建图表
3. `build_conversation` 正确排序和格式化
4. 与 runner.py 的集成点

**Step 1: 读 collectors.py 完整实现**

**Step 2: 运行测试**

```bash
pytest tests/harness/extensions/test_collectors.py -v
```

**Expected:** Collectors 正确从 agent_io 和 chart events 构建数据。

---

## Phase G: 当前分支变更审查

### Task G1: Context Architecture WS 生命周期重构

**Files:**
- Review: `frontend/src/contexts/workflow-context/WorkflowScope.tsx` (diff)
- Review: `frontend/src/components/layout/WorkflowCenterPanel.tsx` (diff)
- Review: `frontend/src/contexts/workflow-context/useWorkflowEvents.ts` (diff)

**审查要点：**
1. WS 从 WorkflowScope 移到 WorkflowCenterPanel — 确认 WS 不再在 workflow 切换时重建
2. `window.__wsMethods` → React Context — 确认不再有全局变量泄漏
3. `window.__useContextArchitecture` 标记已移除 — 确认无残留引用
4. `WSMethodProvider` 使用 React Context 正确传递 send 方法

**Step 1: 确认 WorkflowScope 不再创建 WS**

旧代码在 `WorkflowScopeInner` 中调用 `useScopedWorkflowEvents()`，新代码只提供 stores。

**Step 2: 确认 WS 生命周期在 WorkflowCenterPanel**

`useWorkflowWS(workflowId)` 在 WorkflowCenterPanel 调用，该组件不因 workflow 切换而 remount。

**Step 3: 确认无全局变量引用**

搜索 `__wsMethods` 和 `__useContextArchitecture` 确认已清除。

**Step 4: 运行前端构建**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

**Expected:** WS 生命周期稳定，无全局变量，构建成功。

---

### Task G2: ChatInput Scoped Store 注入

**Files:**
- Review: `frontend/src/components/chat/ChatInput.tsx` (diff)

**审查要点：**
1. Props 优先于 global store — React hooks 规则遵守
2. 所有 store hooks 都被调用（不条件调用）
3. `addUserMsg`, `clearPQ`, `interruptMsg` 正确选择 prop 或 global
4. useCallback 依赖数组完整

**Step 1: 确认 hooks 不条件调用**

检查所有 `useXxxStore` 调用都在组件顶层。

**Step 2: 确认依赖数组完整**

检查所有 `useCallback` 的 deps 包含使用的外部变量。

**Step 3: 确认 prop 优先级逻辑正确**

`propPendingId !== undefined ? propPendingId : globalPendingId` — 当 prop 为 `null` 时优先使用 prop（正确行为，null 是有效值）。

**Expected:** ChatInput 正确支持 scoped 和 global store 两种模式。

---

### Task G3: Collectors 后端持久化

**Files:**
- Review: `harness/extensions/collectors.py` (新增)
- Review: `server/runner.py` (集成点)

**审查要点：**
1. `build_conversation` 从 agent_io 构建 conversation
2. `ChartCollector` 从 Bus ring buffer 收集 chart events
3. runner.py 在 save 时调用 collectors
4. 数据格式与前端期望一致

**Step 1: 读 collectors.py 完整实现**

**Step 2: 读 runner.py 中的调用点**

**Step 3: 运行测试**

```bash
pytest tests/harness/extensions/test_collectors.py -v
```

**Expected:** Collectors 正确从后端数据构建 conversation 和 charts。

---

## 审查产出

每个 Task 完成后，产出：

1. **状态**: ✅ PASS / ⚠️ WARNING / 🔴 BUG
2. **发现**: 描述发现的问题
3. **建议**: 修复建议（如果有）

最终汇总到 `docs/review/009_comprehensive_code_review.md`。

---

## 执行优先级

1. **Phase G** — 当前分支变更（最高优先，影响合并）
2. **Phase B** — 前端状态管理（影响所有 UI 功能）
3. **Phase A** — 前端 UI 组件（用户直接感知）
4. **Phase C** — 后端 API（数据正确性）
5. **Phase D** — WebSocket（实时功能）
6. **Phase E** — 核心引擎（底层稳定性）
7. **Phase F** — 扩展系统（可选项）
