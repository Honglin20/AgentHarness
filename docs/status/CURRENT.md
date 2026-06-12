# Current Task

**当前任务**: Outline Iter Isolation (Plan E) 实现完成，待手动浏览器验证
**状态**: 5 个 Phase 全部完成，155/155 测试通过，tsc/build 通过
**日期**: 2026-06-12
**分支**: `worktree-outline-master-detail`
**计划**: `docs/plans/2026-06-12-outline-iter-isolation.md`

## 已完成（Plan E — iter 维度隔离 + badge 降级）

| Phase | 内容 |
|-------|------|
| P1 | Data Layer — `TodoStep.iteration` 字段；`handleTodoCreated/Replaced` 加 iter 参数；`todoHandlers` 读 `currentIterationByNode` stamp；`replayEvents` 显式 fallback iter=1 |
| P2 | Derivation — `OutlineItem.isLatestIter` 派生；`computeBadges` token/retry 只在 latest iter 显示；`computeStatus` 历史 iter 从 message 推断；`computeActivity` 历史 iter 走 completed fallback；todos 按 iter 过滤 |
| P3 | UI — `NodeBlockCard` 加 `iteration?` prop + `useMemo` 过滤；`AgentDetailView` 透传；Timeline 视图零改动 |
| P4 | Tests — deriveOutlineItems +7 case；新建 `todo.iteration.test.ts`（6 case）；新建 `todoHandlers.iteration.test.ts`（3 case） |
| P5 | Verify — tsc 零错误；vitest 155/155；npm run build 通过；live server 已切到新构建 |

## 待验证（手动浏览器）

- [ ] NAS loop 工作流 — outline 各 iter row 显示独立 todo list；历史 iter 无 token/retry badge；status 推断正确
- [ ] Replay finished loop run — outline 按 messages 正确分 iter；historical iter status 是 completed/failed
- [ ] Timeline 视图无回归 — todo list 显示所有 iter 的 steps
- [ ] 单 iter 工作流 — `isLatestIter === true`，行为与修复前一致

## 已知降级（计划 Non-goals）

- Replay 模式下 todo 全部归 iter=1（事件回放路径不重建 `currentIterationByNode`），outline 仍按 messages 正确分 iter，只是非 iter=1 row 看不到 todo。Live 运行时正常。
- NodeState 元数据（token/retry/duration）未下沉到 iter 维度 — 通过 `isLatestIter` UI 降级处理。未来如需精确 iter 级数据，走 Plan A2（新增 IterState 并行 store）。

## Outline feature（已完成，2026-06-11）

参见 `docs/plans/2026-06-11-outline-master-detail.md`。

## NAS 待做（outline 完成后继续）

| # | 任务 | 状态 |
|---|------|------|
| 1 | ~~TODO 工具~~ | ✅ 已完成 |
| 2 | ~~sub_agent 并行 + worktree 隔离~~ | ✅ 已完成 |
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |

