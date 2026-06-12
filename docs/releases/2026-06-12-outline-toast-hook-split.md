# 2026-06-12 Outline Toast Hook Split (Plan G)

**Branch:** `main`
**Plan:** `docs/plans/2026-06-12-outline-toast-hook-split.md`

修了 Bug 2（waiting agent 二次进入 toast 漏发）和 Arch 1（useAutoFollowSelection 职责越界），同时把原零测试的两个 hook 补齐。

## Changes

### Bug 2 fix — toast identity 改用 questionId

旧逻辑用 `nodeKey` 作 toast 边沿触发的 identity（`prevWaitingKey !== currentWaitingKey`）。`nodeKey = ${nodeId}__iter${iteration}` — 同一 agent 在同一 iter 内第二次 ask_user 时 key 不变，toast 不再触发。

新逻辑用 `questionId`：
- 每个 `ask_user` 调用生成新 questionId → 两次 ask 都触发 toast
- engine 漏 set questionId 时 fallback `__no_qid__${key}`，退化为 key 行为
- 测试覆盖 fallback 路径，未来 engine 回归可观测

### Arch 1 fix — hook 拆分

`useAutoFollowSelection` 原来同时做 auto-select 和 toast（前者受 `autoFollow` 控制，后者不受），名字误导。拆为：

- `useWaitingAgentToast(items)` — 只发 toast，独立于 `autoFollow`
- `useAutoFollowSelection(items)` — 只管 selection

`AgentOutline` 接线两个 hook。consumer 只有这一处，迁移完整。

### 多 waiting agent 优先级 pin

`deriveOutlineItems` 已经按 `firstTs` 升序排，`items.find(waiting)` 自然返回最早 waiting 的 agent。本次加测试 pin 这个契约，防未来 sort key 重构时静默 regression。

### Testing infrastructure

- 装 `@testing-library/react`、`@testing-library/jest-dom`、`happy-dom`
- `vitest.config.ts` 加 `environment: "happy-dom"` 和 `*.test.tsx` include
- 纯 TS 单元测试在 happy-dom 下完全兼容（27 → 38 → 全套 176 全过）

## Commits

- `e70ad3d` refactor(outline): split useAutoFollowSelection + fix Bug 2 (Plan G)
- `56e9671` chore(frontend): install @testing-library/react + happy-dom (Plan G)
- `df5f406` test(outline): hook tests for split hooks (Plan G)

## Verification

- `npx tsc --noEmit` → 零错误
- `npx vitest run src/components/outline` → 38 测试通过（原 27 + 新 11）
- `npx vitest run` (全套 frontend) → 176 测试通过，零 regression

## 偏离 plan 的地方

1. **vitest config 改动超出 plan 预期**：Plan G Task 2.1 假设装 `@testing-library/react` 即可，实际还需 happy-dom + config 扩展（include `*.test.tsx` + environment）。改动 surgical、可逆，且对现有测试零影响（已验证）。

2. **`afterEach(cleanup)`**：Plan G 测试代码没显式写 cleanup。实际发现：多个 hook 实例同时 mount 时，它们的 effects 共享 zustand store 并争抢 `selectedKey`，造成跨测试干扰。加 `cleanup()` 后修复。这是 Plan G 测试代码的小补丁，已 inline 注释说明原因。

## 已知 follow-up

- **Browser 烟测（Plan G Task 1.4 + 3.2）未跑** — 需要用户在 dev server + 实际 ask_user 工作流下验证 toast 行为。Bug 2 的回归 case 已被单元测试覆盖，但实际 UI 行为（autoFollow toggle、tooltip 时机）需手动确认。
- **Arch 4 · AgentDetailView ref 桥接 pattern** — 旧 pattern 复用，可作单独清理任务。
- **j/k 导航无组件测试** — Batch A 加了 listener 重构但没补 e2e 测试，逻辑已被 derive 测试覆盖。
