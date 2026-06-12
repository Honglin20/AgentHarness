# CHANGELOG

索引。详细信息见 [`docs/releases/`](../releases/)。
规则：见 [CLAUDE.md — CHANGELOG 规则](../../CLAUDE.md#changelog-规则)。

每条 1-2 句话 + 链接到对应 release note。

---

## 2026-06

- **2026-06-12** — **Outline Toast Hook Split (Plan G)**：拆 `useAutoFollowSelection` 为 `useWaitingAgentToast` + `useAutoFollowSelection`，toast 边沿触发改用 `questionId`（带 `__no_qid__` fallback），修复同一 agent 二次 ask 时漏 toast 的 Bug 2。补 11 个 hook 测试。
  → [详情](../releases/2026-06-12-outline-toast-hook-split.md)

- **2026-06-12** — **Outline Review Batch A**：3 项 surgical fix（UI 1 border 冲突、Arch 2 keydown listener 改 ref-based、retry badge 加 status 门控）。Plan G (Batch B) 已就绪待执行。
  → [详情](../releases/2026-06-12-outline-review-batch-a.md)

- **2026-06-12** — **Outline Iter Isolation Hardening (Plan F)**：iter 下沉到后端（`node_invocation_counts` state + `node.started` payload + `StepEntry.iteration`），前端从事件读，不再 counter 自增。后端 = 唯一真值，前端 = 渲染投射。
  → [详情](../releases/2026-06-12-outline-iter-hardening.md)

- **2026-06-12** — **Outline Iter Isolation (Plan E)**：`TodoStep.iteration` + `OutlineItem.isLatestIter` 派生 + `NodeBlockCard` 按 iter 过滤 todo。历史 iter 的 token/retry/duration badge 通过 UI 降级处理。
  → [详情](../releases/2026-06-12-outline-iter-isolation.md)

- **2026-06-11** — **Outline + Master-Detail Conversation View**：Linear 风格 agent 列表 + master-detail 切换 + j/k 导航 + auto-follow + ask_user toast。
  → [详情](../releases/2026-06-11-outline-master-detail.md)

---

## 历史（2026-05-27 ~ 2026-06-10）

合并前未拆分的归档，详见 [`docs/releases/HISTORICAL.md`](../releases/HISTORICAL.md)。
