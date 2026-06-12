# 2026-06-12 Outline Review Batch A

**Branch:** `main`
**Scope:** 第一轮 outline review 中属于 surgical fix 的三项，独立 commit。

## Changes

### UI 1 — waiting + selected border 冲突
`OutlineItemRow.tsx:49`：waiting 状态加 `border-amber-500`、selected 加 `border-blue-500`，CSS 顺序让 amber 覆盖 selected。改为 waiting 时 selected 退到只改背景，amber border 保留——ask 比 select 更需要被看见。

### Arch 2 — AgentOutline keydown listener 频繁重绑
`AgentOutline.tsx:29-60`：useEffect deps 含 `items`，而 `useAgentOutline` 每次 derive 返回新数组引用 → 每个 streamed token 都触发 listener 解绑+重绑。改成 items/selectedKey/select 写进 ref，effect deps=`[]`，listener 只绑一次。

### Retry badge status 门控
`deriveOutlineItems.ts:229`：`computeBadges` 原本只看 `retryAttempts.length`，agent 经历 retry 后最终 success 时 badge 仍显示 `2/3`。加 `node.status === "retrying"` 门控，对齐 title 语义（"Retry attempt N+1 of M"）。补一个回归测试覆盖 success-with-history 场景。

## Commits

- `af68c11` fix(outline): waiting + selected 不再争抢 left border (UI 1)
- `1864b85` refactor(outline): AgentOutline keydown listener 改 ref-based (Arch 2)
- `eba949a` fix(outline): retry badge 加 status=retrying 门控 (review finding)

## Verification

- `npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts` → 21 passed（原 20 + 新增 1）
- `npx tsc --noEmit` → 零错误

## 偏离 plan 的地方

无。三项都按 review 评估时的方案落地。

## 已知 follow-up

- **Batch B (Plan G)**：`docs/plans/2026-06-12-outline-toast-hook-split.md` — Bug 2 + Arch 1 的联合修复，~50 min 工作量，待执行。
- **Arch 4 · AgentDetailView ref 桥接 pattern**：旧 pattern 复用，不阻塞，可作单独清理任务。
- **测试盲区**：j/k 导航无测试；`@testing-library/react` 未装（Plan G Task 2.1 处理）。
