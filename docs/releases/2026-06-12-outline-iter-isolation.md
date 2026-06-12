# Release Notes — 2026-06-12 Outline Iter Isolation (Plan E)

**Branch:** `worktree-outline-master-detail`
**Plan:** `docs/plans/2026-06-12-outline-iter-isolation.md`

修复 outline review 中发现的 iter 维度错配问题。会话/活动数据 iter-aware（message + todo），节点元数据（token/retry/duration/status）通过 `isLatestIter` UI 降级处理。

### 改动概要

- **`TodoStep.iteration?: number`** — 新字段，handler 层从 `currentIterationByNode` stamp，与 `ConversationMessage.iteration` 同模式
- **`handleTodoCreated/Replaced`** — 加 `iteration` 参数（必传，explicit）
- **`todoHandlers.ts`** — `todo.created` / `todo.replaced` 读 conversation store stamp iter
- **`replayEvents.ts`** — 事件回放路径显式 fallback iter=1（持久化事件不带 iter）
- **`OutlineItem.isLatestIter`** — 新派生字段，决定 badge/status 走节点级还是降级
- **`computeBadges`** — token / retry badge 只在 latest iter 显示；iteration badge 所有 row 都显示
- **`computeStatus`** — latest iter 用 NodeState；历史 iter 从 messages 推断（done→completed, error→failed, else→idle）
- **`computeActivity`** — 历史 iter 返回 completed（duration 省略）
- **`NodeBlockCard`** — 加 `iteration?` prop，`useMemo` 按 iter 过滤 todos；Timeline 不传 → 显示全部
- **`AgentDetailView`** — 透传 `iteration` 到 NodeBlockCard

### 测试

- `deriveOutlineItems.test.ts` +7 case（todos 过滤、isLatestIter、badge 降级、status 推断、legacy fallback）
- 新建 `todo.iteration.test.ts`（6 case — stamping + 更新不破坏 iter + legacy 数据）
- 新建 `todoHandlers.iteration.test.ts`（3 case — handler 层 stamping + 边缘 ordering）
- 全量 155/155 通过

---

