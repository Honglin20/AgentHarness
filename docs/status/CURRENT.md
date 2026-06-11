# Current Task

**当前任务**: Outline + Master-Detail Conversation View 实现完成，待手动浏览器验证 + merge
**状态**: 全部 6 phase 完成，138/138 测试通过
**日期**: 2026-06-11
**分支**: `worktree-outline-master-detail`
**计划**: `docs/plans/2026-06-11-outline-master-detail.md`

## 已完成（outline feature）

| Phase | 内容 |
|-------|------|
| P1 | Iteration tracking — `iteration` 字段 + `currentIterationByNode` + node.started 递增 |
| P2 | Outline 派生层 — `deriveOutlineItems` 纯函数 + 9 测试 |
| P3 | 选择状态 — `outlineStore` + auto-follow（waiting > running 优先级） |
| P4 | UI 组件 — OutlineItemRow / AgentOutline / AgentDetailView / OutlineMode |
| P5 | 集成 — toggle / reset on view switch / j/k 导航 / ask_user toast |
| P6 | 验证 — 138/138 测试通过，tsc 零错误 |

附带修复：Problem 2 (thinking 单击展开)。

## 待验证

- [ ] 手动浏览器 smoke：outline 渲染、agent 切换、toggle 切换、j/k 导航、ask_user toast
- [ ] 大历史 run 性能 smoke（5-agent run + 历史回放）
- [ ] Merge 到 main（用户决定时机）

## NAS 待做（outline 完成后继续）

| # | 任务 | 状态 |
|---|------|------|
| 1 | ~~TODO 工具~~ | ✅ 已完成 |
| 2 | ~~sub_agent 并行 + worktree 隔离~~ | ✅ 已完成 |
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |
