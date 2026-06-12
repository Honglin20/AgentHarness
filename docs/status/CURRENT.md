# Current Task

**当前任务**: Outline Iter Isolation Hardening (Plan F) 实现完成，待手动浏览器验证
**状态**: 7 个 Phase 全部完成，前端 164/164 测试通过，后端 6/6 测试通过，tsc/build 通过
**日期**: 2026-06-12
**分支**: `worktree-outline-master-detail`
**计划**: `docs/plans/2026-06-12-outline-iter-hardening.md`

## 已完成（Plan F — iter 下沉到后端 + 所有 review findings）

| Phase | 内容 |
|-------|------|
| P1 | B1 — `computeStatus` 把 `interrupted` 视为 `failed`（cancelled iter 不再显示为 idle） |
| P2 | D2 — `pendingQuestionCount` 检查移入 `isLatestIter` 分支（历史 iter 不再显示 waiting-for-user） |
| P3 | D1 — NodeBlockCard 改用 `useShallow` 履约 Performance Contract |
| P4 | B2 Backend — `HarnessState.node_invocation_counts` 字段；node.started payload 带 iteration；StepEntry.iteration 从 deps 注入；AgentDeps.iteration 显式字段；AST 守卫测试覆盖 8 个 node_func return path |
| P5 | B2 Frontend — node.started handler 从事件读 iter（cache 不是 counter）；replayEvents snapshot + event-fallback 都读 iter；NodeStartedPayload 加 iteration 字段；发现并修复 plan 的 two-pass pre-scan bug（multi-iter loop 场景） |
| P6 | Test gaps — T3 stamp misalignment；I1 out-of-order event-fallback；修复 pre-existing TS 错误（2 处 TodoStep fixture） |
| P7 | Verify — 前端 164/164 + 后端 6/6 测试通过；tsc 零错误；build 通过；live server 已切到新构建 |

## 待验证（手动浏览器）

- [ ] NAS loop 工作流 — outline 各 iter row 显示独立 todo list；历史 iter 无 token/retry badge；interrupted iter 显示为 failed
- [ ] Replay finished loop run — outline 按 messages + 持久化 todo_steps 双路径正确分 iter
- [ ] Replay legacy run（pre-Plan-F）— todo 默认 iter=1，outline 仍按 messages 分 iter
- [ ] Timeline 视图无回归 — todo list 显示所有 iter 的 steps
- [ ] 单 iter 工作流 — `isLatestIter === true`，行为与 Plan E 一致

## 已知降级

- **Task 6.2 跳过** — `@testing-library/react` 未安装，NodeBlockCard 组件级测试未写。Derive outline 单元测试已覆盖核心逻辑；建议后续单独安装 testing-library 补 T4。
- **`NodeCompletedPayload.iteration` 未加**（Phase 5 review I2）—— `node.completed` handler 用 `findLastIndex` 找 streaming message，理论上若多 iter 重叠会找错。实际上 LangGraph 不 pipeline 同一 node，不会触发。建议作为 follow-up 文档化或加 invariant 测试。
- **Replay pre-Plan-F run** — events 和 todo_steps 都没 iteration，全部默认 iter=1。outline 仍按 messages 分 iter，但 todo list 全归 iter=1。Live 运行不受影响。

## 关键架构变化

**iter 从前端 counter 变为后端权威**：
- Plan E：`node.started` handler 自增 `currentIterationByNode`（前端 counter）
- Plan F：`node.started` payload 带 `iteration`（后端 `node_invocation_counts` 字段），前端读后缓存

**核心文件**：
- 后端：`harness/engine/state.py`, `harness/engine/node_factory.py`, `harness/engine/node_phases.py`, `harness/tools/todo.py`, `harness/tools/deps.py`
- 前端：`frontend/src/contexts/workflow-context/routing/nodeHandlers.ts`, `frontend/src/contexts/workflow-context/replayEvents.ts`, `frontend/src/types/events.ts`

## Plan E（前一次，已 merge 到本分支）

参见 `docs/plans/2026-06-12-outline-iter-isolation.md`。

## Outline feature（更早，2026-06-11）

参见 `docs/plans/2026-06-11-outline-master-detail.md`。

## NAS 待做（outline 完成后继续）

| # | 任务 | 状态 |
|---|------|------|
| 1 | ~~TODO 工具~~ | ✅ 已完成 |
| 2 | ~~sub_agent 并行 + worktree 隔离~~ | ✅ 已完成 |
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |
