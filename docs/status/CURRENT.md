# Current Task

**当前任务**: 工具与 Token 问题分阶段修复 —— 阶段 2 完成，准备阶段 3
**状态**: 阶段 2（Token 统计语义分离）已落地；阶段 3（工具结果截断）待启动
**日期**: 2026-06-16
**分支**: `main`

## 阶段进度总览

| 阶段 | 任务 | 状态 | Commit |
|---|---|---|---|
| 1 P0 | ask_user emit chat.answer/timeout + 超时 env + stdin fallback | ✅ | `af923ad` |
| 1 P1 | review follow-ups（float timeout / EOF raise / stdin lock） | ✅ | `01b5c6d` |
| 2 | Token 统计语义分离（cost vs window） | ✅ | （本提交） |
| 3 | 工具结果截断（bash/codegraph_explore 长输出截断） | 待开始 | — |
| 4 | 自动 compaction（评估中） | 待评估 | — |

## 阶段 2 完成情况

**核心改动**：
- 后端 `LLMExecutor` 加 baseline + delta，emit 时携带 `last_input` / `last_output` / `cache_hit`
- 后端 `node_factory.token_usage` dict 扩展（cumulative / last / cache_hit）
- 前端 `workflowStore.NodeState.tokenUsage` + `setNodeUsage` 扩展
- 前端 `settingsStore.modelContextLimit`（默认 200k）
- 前端 `BudgetBar` 拆双进度条：Cost（累计 / envelope）+ Window（max 单次 / 模型上限）

**验证**：
- 后端 78 测试全过（含 5 个新增 stage-2 测试）
- 前端 8 routing 测试全过（含 2 个新增 stage-2 路由测试）
- TypeScript 类型干净 / frontend build 成功

详见 [`docs/releases/2026-06-16-token-stats-semantic-split.md`](../releases/2026-06-16-token-stats-semantic-split.md)

## 必读文件（阶段 3 启动前）

- `docs/plans/2026-06-16-tooling-token-phase-plan.md` — 全四阶段计划
- `harness/engine/llm_executor.py:440-455` — `_emit_tool_result`（截断入口）
- `harness/tools/bash.py` / `harness/tools/grep_glob.py` / `harness/tools/mcp_bridge.py`（MCP tool result）— 长输出源头
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/token-stats-vs-context-window.md` — 根因

## 阶段 3 待启动：工具结果截断

**目标**：从源头降低 message_history 增长速度，让 window 不容易炸。

**要点**：
- 新增 `harness/tools/_truncate.py`：按工具类型应用阈值（bash 8KB / codegraph_explore 6KB / sub_agent 4KB / Read 不截断）
- 在 `LLMExecutor._emit_tool_result` 入口处应用
- 截断时附加提示："Result truncated to N KB. Use codegraph_node for full source."
- emit `agent.tool_output_truncated` 事件（已在 CRITICAL_EVENT_TYPES，前端可提示）

**预计工作量**：1 天

## 旁路

- 阶段 1 review 标记的 3 个 P2 推后项仍跟踪（chat.answer dev warning / rawToAnswer legacy 双模式 / 端到端 WS replay 集成测试）
- NAS workflow ONNX 已完成，等下次跑 NAS 实测验收
- Pre-existing 测试失败（test_chart × 3, test_sub_agent × 1, 前端 workflowHandlers import 问题）单独跟踪

## 旁路：NAS run 实测发现 + Harness 架构问题（2026-06-16）

跑完 NAS workflow（timeseries / cifar_cnn）后梳理出 5 个跨 NAS 业务层 / Harness 框架层的问题，**已写完整分析待排期**，与当前阶段 3 任务**并行跟踪**，不冲突。

详细分析与修复方案见 [`docs/plans/2026-06-16-nas-run-findings-and-arch-issues.md`](../plans/2026-06-16-nas-run-findings-and-arch-issues.md)。

### NAS Workflow 问题（业务设计层）

- **#1 Latency 目标 HITL 缺失**：cycle 非交互前提下，把"目标确认 + 宽放策略"上提到 setup（scout）一次性捕获，cycle 内 `check_target.py` deterministic 判定。建议用 LangGraph `interrupt()` 而非 ask_user。**P1 / 1.5-2 天**
- **#3 Coder + Runner sub_agent 合并（fast_mode）**：用户提议把 coder sub_agent 写完 diff 后直接跑 training，省掉 trainer 重新 spawn runner。客观判断：部分场景合理但不应作默认，建议保留解耦默认 + 新增 `fast_mode` 配置。**P2 / 2-3 天**

### Harness 架构问题（通用框架层）

- **#2 HITL 机制盘点**：框架已有 LangGraph `interrupt()` 路径（`workflow_runtime.py:130-134`）+ 预留事件类型（`workflow.interrupted` / `workflow.waiting_for_guidance`），但**零业务调用方**。问题 #1 实施时顺带启用。跟随 #1
- **#4 CRITICAL_EVENT_TYPES 错分类**：`agent.tool_call` / `tool_result` / `todo.*` / `chart.render` / `bash.background_completed` 等被错标 critical，导致 buffer 单调增长、刷新 replay 风暴。不会导致数据错误，但长跑后刷新慢。重分类前需验证前端 sidecar 兜底。**P1 / 半天-1 天**
- **#5 历史切到运行中切不过去（Bug）**：`useAppViewStore` 与 `useViewStore` 不同步 —— `activateRun` running 分支没调 `showLive()`，`useActiveWorkflowId()` 优先读 useViewStore 仍返回 history runId。单行修复：`activateRun.ts:85` 加 `useViewStore.getState().showLive()`。**P0 / 半小时**

### 建议执行顺序

P0（#5 单行修复）→ P1（#4 重分类 + #1 setup HITL）→ P2（#3 fast_mode）。可与阶段 3 工具结果截断并行排期。

## 旁路：长 Run Replay 架构专项（2026-06-16，单独立项）

问题 #4 的"方案 A 重分类"只是 80% 解，长 run（NAS 200+ iter）刷新仍可能 1-2s。用户决策**从根本上解决** —— 刷新延迟与 run 长度完全解耦。单独立项，4 phase 共 11-14 天。

详细计划见 [`docs/plans/2026-06-16-long-run-replay-architecture.md`](../plans/2026-06-16-long-run-replay-architecture.md)。

**核心架构**：Snapshot + Incremental + On-demand（L1 Hot critical / L2 Warm FIFO 1000 + snapshot 摘要 / L3 Cold sidecar 按需查）

**目标态**：刷新 O(1) < 500ms（无论 run 长度）｜ Cycle 多轮 → 主视图显 latest iter，下拉切历史 iter ｜ Conversation 按 iter 隔离 ｜ Fitness 全量进 snapshot ｜ 放弃"完整回放模式"。

**Phase 进度**：

| Phase | 工作量 | 状态 | Commit |
|---|---|---|---|
| 1 事件分层 + Snapshot API + WS cursor | 4-5 天 | ✅ 完成 | `808e6f7` + `1b57e1b` |
| 2 后端 Cycle iter 持久化 + 查询 API | 2-3 天 | ✅ 完成（backend） | `7062d51` |
| 3a Conversation 历史分页（解决 Phase 2 limitation） | 半天 | ✅ 完成 | `5d8f28c` |
| 3b 前端 iter 下拉 + Conversation 按 iter 隔离 | 2-3 天 | ⏸️ 待启动（依赖事件 iter 标签） | — |
| 4 Fitness 全量 + Chart 按需 | 2 天 | ⏸️ 待启动 | — |

包含原问题 #4 的重分类作为 Phase 1 第一步；原问题 #5（activateRun showLive）是 Phase 1 前置 surgical fix，已落地。

### Phase 3a 完成内容（`5d8f28c`）

后端 snapshot 加 `conversation_total`；前端 `hydrateFromSnapshot` 据此设置 `hasEarlier`。`ScopedConversationTab` 已有的 "Load earlier messages" 按钮自动生效 → 用户刷新后能滚动加载更早消息。

**已知事实**：原计划的 iter 下拉切换器已经存在（`OutlineMode` 左侧 outline 列表就是 iter 切换器，`OutlineItemRow` 通过 iteration badge 显示 "#N"），不需要新建。

### Phase 3b 待启动（依赖事件 iter 标签）

conversation 按 iter 隔离需要每个事件携带 iter 字段（Phase 2 跳过的原 Task #3）。当前 conversation message 已有 `iteration` 字段（`AgentDetailView` 已使用），但事件流到 conversation message 的映射在 collector 层，需要审计。

**实施清单**：
1. 事件持久化时打 iter 字段（`harness/run_store.py` events 写入路径）
2. `useConversationMessages` 按 `selectedIter` 过滤
3. （可选）`AgentDetailView` 调 `/iters/{n}` 拿后端持久化的 input_prompt 完整内容

### Phase 4 待启动：Fitness 全量 + Chart 按需

- 后端 `_save_incremental` 写 `fitness_history`（从 judger agent_io 提取）
- 前端 `FitnessChart` 全量渲染（200 iter ≈ 6KB）
- 详细 chart（loss_curve / latency_breakdown）按 iter 切换时按需查 sidecar
