# Current Task

**当前任务**: 执行 Plan G (Batch B) — outline toast hook 拆分
**状态**: Batch A 已合入 main；Batch B plan 已写好待执行
**日期**: 2026-06-12
**分支**: `main` (HEAD: `3175935`)

## 必读文件

- `docs/plans/2026-06-12-outline-toast-hook-split.md` — **Plan G（待执行）**
- `docs/releases/2026-06-12-outline-review-batch-a.md` — Batch A 产出（已合入）
- `CLAUDE.md` — 协作规则 + CHANGELOG 规则

## 当前 focus

执行 Plan G（~50 min）：

1. **Phase 1**：拆 `useWaitingAgentToast` + 瘦身 `useAutoFollowSelection` + 在 `AgentOutline` 接线 + 手测烟测
2. **Phase 2**：11 个新测试（`useWaitingAgentToast.test.tsx` 6 + `useAutoFollowSelection.test.tsx` 5）
3. **Phase 3**：验证 + 写 release note + 更新 CHANGELOG/CURRENT

关键决策已在 plan 里固化：
- **Decision 2**：toast identity 用 `questionId`，带 `__no_qid__${key}` fallback 防 engine 漏 set
- **Decision 4**：toast 完全脱离 `autoFollow`（pin 状态下仍提示）

## 已知 follow-up（小，不阻塞）

- **Arch 4 · AgentDetailView ref 桥接 pattern** — 旧 pattern 复用，可作单独清理任务
- **j/k 导航无组件测试** — Batch A 加了 listener 重构但没补组件测试，逻辑已被 derive 测试覆盖
- **`@testing-library/react` 未装** — Plan G Task 2.1 会处理；若被阻塞，fallback 到 `react-test-renderer` 的 `renderHook`

## NAS 待做（项目级）

| # | 任务 | 状态 |
|---|------|------|
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |
