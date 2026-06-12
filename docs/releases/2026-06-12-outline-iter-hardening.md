# Release Notes — 2026-06-12 Outline Iter Isolation Hardening (Plan F)

**Branch:** `worktree-outline-master-detail`
**Plan:** `docs/plans/2026-06-12-outline-iter-hardening.md`

修复 Plan E review 中的所有 findings，把 `iteration` 概念从前端 counter 下沉到后端权威源。

### 改动概要

**后端（Phase 4）**：
- `HarnessState.node_invocation_counts` 新字段（universal invocation counter，与 conditional_edge 的 `iteration_counts` 区分）
- `node_func` 启动时自增 counter；8 个 return path 全部包含更新（AST 守卫测试防回归）
- `build_node_started_payload` 加 `iteration` 参数 + payload 字段
- `StepEntry.iteration` 字段，create/replace 时从 `deps.iteration` 注入
- `AgentDeps.iteration: int = 1` 显式字段（消除 silent failure 风险）

**前端（Phase 5）**：
- `node.started` handler 从 payload 读 iteration（cache 不是 counter）
- `replayEvents` snapshot 路径读持久化 `iteration` 字段
- `replayEvents` event-fallback 路径用 single-pass（发现并修复 plan 的 two-pass pre-scan bug，multi-iter loop 场景会丢 iter）
- `NodeStartedPayload.iteration?: number` 类型字段

**Bug fixes（Phase 1-3）**：
- B1: `computeStatus` 历史 iter 推断把 `interrupted` 视为 `failed`（cancelled iter 不再显示 idle）
- D2: `pendingQuestionCount` 检查移入 `isLatestIter` 分支（历史 iter 不再错误显示 waiting-for-user）
- D1: NodeBlockCard 改用 `useShallow` 履约 Plan E 的 Performance Contract

**测试（Phase 6）**：
- T3: stamp misalignment 降级行为文档化
- I1: out-of-order event-fallback 防御性测试
- 修复 2 处 pre-existing TS 错误（TodoStep fixture 类型）

### Commits

后端：1788be0, 3910767, 9a7b357, 7d39afb, 5b20d32, 1fb6689, 238fef1, de03b19, 1917028
前端：6f23952, f82a68e, b3498c8, b41ee4c, 9961745, 58cfab2, f0bdc05, 6e073bd, c23ba0e, a10f95f

### 验证

- 前端：164/164 vitest 通过；tsc 零错误；build 通过
- 后端：6/6 pytest 通过（含 AST 守卫 + reducer + StepEntry stamping）

### 已知降级 / Follow-up

- Task 6.2（NodeBlockCard 组件级测试）跳过 — `@testing-library/react` 未安装
- `NodeCompletedPayload.iteration` 未加（I2）—— LangGraph 不 pipeline 同 node，实际不触发，建议作为 invariant 测试 pin

---

