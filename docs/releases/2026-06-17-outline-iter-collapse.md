# Outline Iter Collapse + Node Iter Dropdown

> 日期：2026-06-17
> 类型：feature
> 计划：[`docs/plans/2026-06-17-outline-iter-collapse.md`](../plans/2026-06-17-outline-iter-collapse.md)
> 起：[`2026-06-16-long-run-replay-architecture.md`](../plans/2026-06-16-long-run-replay-architecture.md) Phase 3 主体

## 背景

长 loop workflow（NAS：selector / planner / trainer / judger 各跑 N 轮）下，outline 把每个 iter 平铺成独立 row —— 50 iter × 4 agent = 200 行 sidebar list，噪音大、j-k 导航累。

后端 Phase 2（commit `7062d51`）早已就绪：iter sidecar + iter_index + `GET /runs/{id}/nodes/{node}/iters[/n]` + snapshot mirror。本 release 把前端 UI 闭环。

## 实际做了什么

### Sidebar：折叠 + ⇡N badge

同一 nodeId 的多 iter 折叠成 1 行，badge 显示 `⇡N`（替代原 per-iter `#N` iteration badge）。latest iter 的 retry / tokens badge 仍然显示。

```
┌─ Agents ──────────┐
│ selector   ⇡3     │
│ planner    ⇡3     │
│ trainer    ⇡3     │
│ judger     ⇡2     │
└───────────────────┘
```

### Detail Panel：iter dropdown

`AgentDetailView` 顶部新增 sticky bar（多 iter 才显示），内含 `NodeIterSelector` dropdown：

```
┌─ selector  ⌄ Iter 3 (latest) ───┐
├──────────────────────────────────┤
│ [iter 3 content / conversation]  │
└──────────────────────────────────┘
```

- 默认显示 latestIter；用户切到 iter N 后，选择**按 nodeId 保留** —— 切到别的 agent 再切回来，仍停在 iter N
- 单 iter agent 不渲染 bar（决策 4）
- 数据从 `OutlineGroup.iters`（Phase 1 派生）读，**不调 API**（决策 5 严格落地）

## 实施清单

| Phase | 文件 | 说明 |
|---|---|---|
| 1 | `groupOutlineByNode.ts` (新) + 9 tests | 按 nodeId 折叠 OutlineItem[] → OutlineGroup[] |
| 1 | `types.ts` | 新增 `OutlineGroup` interface |
| 2a | `OutlineGroupRow.tsx` (新) | 替代 `OutlineItemRow.tsx`（已删），渲染 group.latest + ⇡N badge |
| 2b | `NodeIterSelector.tsx` (新) | Radix Select dropdown |
| 3 | `outlineStore.ts` | `selectedKey` → `selectedNodeId` + `selectedIterByNode: Record` + `selectIter` action |
| 3 | `OutlineMode.tsx` / `AgentOutline.tsx` | 全部 callsite 迁移到 selectedNodeId + group |
| 4 | `AgentDetailView.tsx` | 删 `iteration` prop；接收 `{nodeId, latestIteration, iterCount, iters}`；顶部 sticky IterBar |
| 5 | `useAgentOutline.ts` | 返回 `OutlineGroup[]`（末端加 `groupOutlineByNode`） |
| 5 | `useAutoFollowSelection.ts` / `useWaitingAgentToast.ts` | 接收 group[]；follow / toast 基于 `group.latest` |
| 测试 | `outlineStore.test.ts` / `useAutoFollowSelection.test.tsx` / `useWaitingAgentToast.test.tsx` | 全部 fixture + 断言迁移到 group / selectedNodeId |

## 偏离 plan 处

| Plan | 实际 | 原因 |
|---|---|---|
| 决策 5：iter 数据从 `workflowStore.iterIndex` 读 | 直接从 `OutlineGroup.iters` 读 | `hydrateFromSnapshot` 还没消费 `nodes_latest` / `iter_index` 字段；`OutlineGroup.iters`（Phase 1 派生）已经含完整 iter 列表，复用更简单，不需要新加 hydration 路径。后续 Phase 2 frontend（DAG 节点 latestIter 标记）需要时再补 hydrate |
| Phase 4：从 store 读 latestIter，删 iteration prop | 通过 props 传 `latestIteration + iterCount + iters` | OutlineMode 已经从 group 选好了，把 group 的字段直接传下来比 store 二次查找更直接，少一个 store 订阅 |

## 验证

- **outline 测试**：57/57（含 9 个新 `groupOutlineByNode` + 9 个新 `outlineStore` 行为 + 6 个 useAutoFollowSelection 含 group.latest follow）
- **全量前端测试**：260/260（去除已知 flaky `outlineBenchmark.test.ts` 的 stress workload timing —— 全量 suite 环境慢时该 timing 测试会 flaky；单独跑稳定通过）
- **TypeScript**：0 个 outline 相关错误（pre-existing PortalState 错误与本 release 无关）
- **Build**：`npm run build` 通过

## 关键决策回顾

1. **折叠在 view 层做**：不动 sidecar / deriveOutlineItems schema（追加写入效率 + live/replay 都不改）
2. **`selectedIterByNode` 是 Record**：切 agent 保留每个 agent 用户选的 iter（否决单值重置方案）
3. **默认 latest，不做 auto-follow latest**：避免跑新 iter 时打断用户当前阅读
4. **单 iter agent 不渲染 dropdown bar**：避免无意义可点击 UI
5. **iter dropdown 数据从 `OutlineGroup.iters` 读**：决策 5 严格落地，0 API call

## Scope 外（独立 PR）

- DAG view 节点 `latestIter/totalIters` 标记
- `hydrateFromSnapshot` 消费 `nodes_latest` / `iter_index` 字段（若 DAG view 要做时一起做）

## Commit SHA

（待 commit）
