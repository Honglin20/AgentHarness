# Current Task

**当前任务**: conversation ↔ TODO 联动架构修复（阶段 1-4 已完成）
**状态**: ✅ 后端 + 前端联动 + 端到端验证全部通过；待用户跑真实 workflow 验收
**日期**: 2026-06-10

---

## 已完成（4 阶段）

### 阶段 1: 后端 TODO 工具扩展 (R2) ✅
- `harness/tools/todo.py`: op 加 `complete_remaining` + `replace`，status 加 `skipped`
- `harness/extensions/bus.py`: CRITICAL_EVENT_TYPES 加 `todo.bulk_completed` + `todo.replaced`

### 阶段 2: 后端 step gate + schema 迁移 (R1) ✅
- `harness/engine/step_gate.py` (新建): `step_gate_validator` 作为 pydantic-ai output_validator
  - Gate 1: `has_plan == False` → ModelRetry
  - Gate 2: 存在 non-terminal step → ModelRetry
- `harness/engine/micro_agent.py`: 注入 validator + `retries={'tools': N, 'output': 1}`
- `harness/engine/llm.py`: `retries` 接受 dict
- `harness/engine/node_factory.py`: 删除手工 `validate_output`（迁移到 validator，享受 retry）

### 阶段 3: 前端联动 (R7/R9) ✅
- `frontend/src/types/events.ts` + `eventSchemas.ts`: 加 `todo.bulk_completed` + `todo.replaced` 类型
- `frontend/src/contexts/workflow-context/stores/todo.ts`: TodoStepStatus 加 `skipped`，新增 `handleTodoBulkCompleted` + `handleTodoReplaced`
- `frontend/src/contexts/workflow-context/routing/todoHandlers.ts`: 新事件 handler + **R9 修复**（step terminal 时清理 currentStepIdByNode）
- `frontend/src/components/conversation/AgentQuestionCard.tsx`: **R7 修复** — 默认 collapsed 从 "auto" 改为 `false`（ask_user 永远展开）
- `frontend/src/components/conversation/ScopedConversationTab.tsx` + `TodoStepList.tsx`: 加 `skipped` 图标

### 阶段 4: 端到端验证 ✅
- `.spike_model_retry.py`: 证明 streaming/non-streaming 路径 ModelRetry 都触发 retry
- `.spike_retry_budget.py`: 证明 `output_retries=1` 严格生效（2 次 LLM 调用终止）

## 验证状态

- **后端 pytest**: 49/50 通过（1 个 pre-existing failure: `test_error_context.py` 用了 Python 3.12 已移除的 `asyncio.coroutine`，与本次改动无关）
- **前端 vitest**: 111/111 通过
- **前端 tsc**: 零错误

## 待用户验证

跑一个真实的 multi-agent workflow，观察：
1. agent 没调 todo.create → 应该看到 retry 提示，最终 `node.failed` (NoTodoPlan)
2. agent 提前完成目标 + 调 `complete_remaining` → 顺利进入下一个 agent
3. ask_user 卡片默认展开（不再被 compact 隐藏）
4. 切换 agent 不再显示重复 analyzer 块（如果仍复现，需要做 R6）

## 已知未做（按 ADR 排序）

| 项 | 状态 | 原因 |
|----|------|------|
| R6（删除 nodeHandler 冗余 addAgentMessage）| 暂跳过 | 等 R1+R2+R7 上线后看是否还复现；如果复现再做（避免影响 WS 重连兜底）|
| R10（删除 forceTerminalSteps）| 保留 | A1 hard gate 后新 run 不需要，但作为老 run hydration 兜底保留 |
| system_prompt 强化 | 部分 | todo.py description 已强化"必须 op='create'"；如需更强可在 `augmented_prompt` 加固定段 |
| R3+R4+R5（snapshot-first hydration）| 排期 | 影响面大，独立做 |

## 必读文件

- `docs/plans/2026-06-10-conversation-todo-arch-fix.md` — **根因报告**
- `docs/plans/2026-06-10-todo-step-gate-adr.md` — **本次实施的 ADR**
- `harness/engine/step_gate.py` — step gate validator
- `harness/tools/todo.py` — TODO 工具新 op
- `harness/engine/micro_agent.py:54-71` — validator 注入点
- `frontend/src/contexts/workflow-context/routing/todoHandlers.ts` — 前端 todo 事件路由
- `frontend/src/components/conversation/AgentQuestionCard.tsx:44` — ask_user 默认展开
