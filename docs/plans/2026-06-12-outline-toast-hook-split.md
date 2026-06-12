# Outline Toast Hook Split (Plan G — Batch B)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Bug 2 (waiting agent 二次进入 toast 漏发) and Arch 1 (useAutoFollowSelection 职责越界) as one atomic change. Split the hook into two single-responsibility hooks, switch the toast edge-trigger from `nodeKey` to `questionId`, and add the first tests for `useAutoFollowSelection` / `useWaitingAgentToast`.

**Scope:** ~45 min of focused work. One new file, one edited file, one consumer update, one new test file.

---

## Why these two are atomic

Bug 2's fix lands on the toast-effect logic. The toast-effect logic currently lives inside `useAutoFollowSelection` — a hook whose name promises "auto-follow selection" but actually does two unrelated things:

1. Auto-select running / waiting items when `autoFollow` is on.
2. Fire a `toast.info` on the waiting-for-user transition, **regardless** of `autoFollow`.

Fixing Bug 2 in place means adding more logic to an already-misnamed hook. Splitting the hook without fixing Bug 2 means the new `useWaitingAgentToast` ships with the same broken edge-trigger. So we do both at once.

---

## Architecture Decisions

### Decision 1: Two hooks, single-responsibility

```ts
// useWaitingAgentToast(items) — fires toast on new question transition.
//   Independent of autoFollow. Name says what it does.
// useAutoFollowSelection(items) — auto-selects per autoFollow switch.
//   No side effects beyond selection. Name says what it does.
```

Consumer (`AgentOutline`) wires both:

```ts
const items = useAgentOutline();
useWaitingAgentToast(items);
useAutoFollowSelection(items);
```

**Rejected alternative — rename to `useConversationSideEffects`:**
Keeps the bundle intact under a more honest name. Cheaper but doesn't fix the
"two unrelated behaviors in one hook" problem. Bug 2 still lands in tangled
code. We pay the split cost once instead.

### Decision 2: Toast identity is `questionId`, not `nodeKey`

Current edge trigger:

```ts
if (waiting && prevWaitingKeyRef.current !== waiting.key) { toast.info(...) }
```

`waiting.key = ${nodeId}__iter${iteration}`. Non-loop scenario: agent A asks in
iter=1, user answers, A asks again — still `A__iter1`, toast doesn't fire.

New edge trigger:

```ts
const currentQuestionId = waiting?.activity.kind === "waiting-for-user"
  ? (waiting.activity.questionId || `__no_qid__${waiting.key}`)
  : null;

if (currentQuestionId && prevQuestionIdRef.current !== currentQuestionId) {
  toast.info(...);
}
prevQuestionIdRef.current = currentQuestionId;
```

**Why questionId:** Each `ask_user` call generates a fresh questionId (UUID in
`agentHandlers.ts`). Two consecutive asks by the same agent necessarily produce
different questionIds → toast fires for both. This is the most precise identity
we have.

**Why the `__no_qid__${key}` fallback:** Defends against engine regressions
where `questionId` is unset on a question message. The fallback degrades to the
current nodeKey-based behavior for that question only — strictly better than
silently dropping the toast. If we ever observe this fallback firing in
production, it's a signal that the engine contract (`questionId` always set on
type=question messages) needs hardening.

**Rejected alternative — `(wasWaiting, isWaiting)` boolean edge:**

```ts
if (!wasWaiting && isWaiting) { toast.info(...) }
```

Risk: React may batch renders such that the "agent A no longer waiting"
intermediate frame never commits before "agent A waiting again". The boolean
edge misses the second ask. questionId is robust to batching because it's a
stable value carried on the message, not derived from render state.

**Rejected alternative — count of pending questions:**

```ts
if (currentPendingCount > prevPendingCount) { toast.info(...) }
```

Two new questions in one batch fires once (count goes 0 → 2). Two separate
ask_user calls in rapid succession fire once. Same batching problem as boolean
edge, plus count is fragile.

### Decision 3: Multi-waiting priority uses smallest `firstTs`

When multiple items have `status === "waiting-for-user"`, `items.find(...)`
returns the first in array order. `deriveOutlineItems` already sorts by
`firstTs` ascending, so "first in array" = "earliest waiting". This matches
user expectation: the agent that's been waiting longest gets the toast.

No code change needed for this — it falls out of the existing sort. But we add
a test to pin the contract so a future refactor of `deriveOutlineItems`'s sort
key doesn't silently regress it.

### Decision 4: `autoFollow` no longer affects toast

Today, toast fires unconditionally (good). After the split, this stays true —
`useWaitingAgentToast` doesn't read `autoFollow` at all. This is the intended
behavior: even when the user has pinned their selection, they still need to
know an agent is waiting. We add a test for this so it doesn't drift.

---

## Robustness Contract

- **Backwards compat (consumer):** `AgentOutline` is the only caller of
  `useAutoFollowSelection`. Updating it to call both hooks is the entire
  migration. No other consumers to touch.
- **Backwards compat (toast behavior):** First-time waiting agent fires toast
  — same as today. Second-time-same-agent-with-new-question fires toast —
  Bug 2 fix. Same-agent-same-question-doesn't-fire — same as today.
- **Engine contract assumption:** `questionId` is set on every
  `type === "question"` message. If unset, fallback kicks in (`Decision 2`).
  Test covers the fallback path.
- **Test coverage:** Every behavior of the new hooks gets a test. The old hook
  had zero tests — this plan closes that gap.

---

## Phase 1: Split the hook + fix Bug 2

### Task 1.1: Create `useWaitingAgentToast.ts`

**Files:**
- Create: `frontend/src/components/outline/useWaitingAgentToast.ts`

**Step 1: Write the new hook**

```ts
/**
 * useWaitingAgentToast — fire a toast the first time a NEW pending question
 * appears on any outline item. Independent of autoFollow.
 *
 * Identity for "new": the questionId carried on the waiting item's activity.
 * Each ask_user call generates a fresh questionId, so two consecutive asks
 * by the same agent both produce toasts. Falls back to `${item.key}` if
 * questionId is missing (engine regression guard — see Decision 2 in
 * docs/plans/2026-06-12-outline-toast-hook-split.md).
 */
"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { OutlineItem } from "./types";

export function useWaitingAgentToast(items: OutlineItem[]): void {
  const prevQuestionIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Multi-waiting priority: items are sorted by firstTs ascending in
    // deriveOutlineItems, so find() returns the earliest-waiting agent.
    const waiting = items.find((i) => i.status === "waiting-for-user");

    const currentQuestionId = waiting?.activity.kind === "waiting-for-user"
      ? (waiting.activity.questionId || `__no_qid__${waiting.key}`)
      : null;

    if (currentQuestionId && prevQuestionIdRef.current !== currentQuestionId) {
      toast.info(`${waiting!.name} is waiting for your answer`, {
        description: "Click the highlighted agent in the outline to respond.",
        duration: 8000,
      });
    }
    prevQuestionIdRef.current = currentQuestionId;
  }, [items]);
}
```

**Step 2: Commit (new file, no behavior change yet — old hook still in place)**

```bash
git add frontend/src/components/outline/useWaitingAgentToast.ts
git commit -m "feat(outline): add useWaitingAgentToast hook (Plan G scaffolding)"
```

### Task 1.2: Slim `useAutoFollowSelection.ts` to selection-only

**Files:**
- Modify: `frontend/src/components/outline/useAutoFollowSelection.ts`

**Step 1: Replace the entire file body**

```ts
/**
 * useAutoFollowSelection — when autoFollow is on and a new "running" or
 * "waiting-for-user" item appears, automatically select it.
 *
 * Selection priority (highest first):
 *   1. waiting-for-user  — never miss an ask_user
 *   2. running           — follow active work
 *   3. (no auto-select for completed/failed/idle)
 *
 * When autoFollow is off, this hook does nothing — user's manual selection
 * sticks.
 *
 * Toast notifications for waiting agents live in useWaitingAgentToast
 * (split out so this hook has a single responsibility and so toast behavior
 * is independent of the autoFollow switch).
 */
"use client";

import { useEffect } from "react";
import { useOutlineStore } from "./outlineStore";
import type { OutlineItem } from "./types";

export function useAutoFollowSelection(items: OutlineItem[]): void {
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const select = useOutlineStore((s) => s.select);
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  useEffect(() => {
    if (!autoFollow) return;

    // Priority 1: any waiting-for-user item.
    const waiting = items.find((i) => i.status === "waiting-for-user");
    if (waiting) {
      if (selectedKey !== waiting.key) select(waiting.key, true);
      return;
    }

    // Priority 2: the most-recently-started running item.
    const running = items
      .filter((i) => i.status === "running")
      .sort((a, b) => b.order - a.order)[0];
    if (running && selectedKey !== running.key) {
      select(running.key, true);
    }
  }, [items, autoFollow, selectedKey, select]);
}
```

**Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/useAutoFollowSelection.ts
git commit -m "refactor(outline): slim useAutoFollowSelection to selection-only (Plan G)"
```

### Task 1.3: Wire both hooks in `AgentOutline`

**Files:**
- Modify: `frontend/src/components/outline/AgentOutline.tsx`

**Step 1: Update imports and call site**

Find:

```tsx
import { useAutoFollowSelection } from "./useAutoFollowSelection";
```

Add immediately below:

```tsx
import { useWaitingAgentToast } from "./useWaitingAgentToast";
```

Find:

```tsx
  const items = useAgentOutline();
  useAutoFollowSelection(items);
```

Replace with:

```tsx
  const items = useAgentOutline();
  useWaitingAgentToast(items);
  useAutoFollowSelection(items);
```

**Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/AgentOutline.tsx
git commit -m "feat(outline): wire useWaitingAgentToast in AgentOutline (Plan G)"
```

### Task 1.4: Manual smoke check (before tests)

At this point the split is in place but no tests exist. Before writing tests,
load the app and confirm toast behavior in a quick smoke pass:

```bash
cd frontend && npm run dev
```

Hard refresh (Cmd+Shift+R). Trigger an `ask_user` from any agent → toast should
appear. Answer → toast clears. Trigger a second `ask_user` from the **same**
agent (without autoFollow toggled) → toast should appear again. (This is the
Bug 2 regression check.)

If the second toast doesn't fire, the fix is broken — investigate before
writing tests.

---

## Phase 2: Tests for the split hooks

### Task 2.1: Install render-testing utilities (if missing)

**Step 1: Check**

```bash
cd frontend && grep -q "@testing-library/react" package.json && echo "present" || echo "missing"
```

If `present`, skip to Task 2.2.

If `missing`, install:

```bash
cd frontend && npm install --save-dev @testing-library/react @testing-library/jest-dom
```

Note: if the project policy is to avoid `@testing-library/react`, fallback to
Task 2.3 (logic-only test that drives the hook via a small test harness using
`renderHook` from `react-test-renderer`). The logic-only path covers Bug 2's
regression; the visual path additionally guards against `AgentOutline` wiring
mistakes.

### Task 2.2: Write `useWaitingAgentToast.test.tsx`

**Files:**
- Create: `frontend/src/components/outline/__tests__/useWaitingAgentToast.test.tsx`

**Step 1: Write the test**

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useWaitingAgentToast } from "../useWaitingAgentToast";
import type { OutlineItem } from "../types";

// Mock sonner.toast so we can assert on calls without spawning real toasts.
const toastInfo = vi.fn();
vi.mock("sonner", () => ({ toast: { info: (...args: unknown[]) => toastInfo(...args) } }));

function waitingItem(name: string, questionId: string, key?: string): OutlineItem {
  return {
    key: key ?? `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
    badges: [],
    order: 0,
  };
}

function idleItem(name: string): OutlineItem {
  return {
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "idle",
    activity: { kind: "idle" },
    badges: [],
    order: 0,
  };
}

// renderHelper re-renders the hook with a new items array.
function renderHelper() {
  let current: OutlineItem[] = [];
  const result = renderHook(({ items }: { items: OutlineItem[] }) => {
    useWaitingAgentToast(items);
  }, { initialProps: { items: current } });
  return {
    setItems: (next: OutlineItem[]) => {
      current = next;
      result.rerender({ items: next });
    },
  };
}

describe("useWaitingAgentToast", () => {
  beforeEach(() => { toastInfo.mockClear(); });
  afterEach(() => { vi.clearAllMocks(); });

  it("fires toast on first waiting item", () => {
    const h = renderHelper();
    h.setItems([waitingItem("analyzer", "q1")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(
      "analyzer is waiting for your answer",
      expect.objectContaining({ duration: 8000 }),
    );
  });

  it("Bug 2 fix — same agent, second question, still fires", () => {
    const h = renderHelper();
    h.setItems([waitingItem("analyzer", "q1")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // User answers → no waiting.
    h.setItems([idleItem("analyzer")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Same agent asks again with a new questionId.
    h.setItems([waitingItem("analyzer", "q2")]);
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });

  it("does NOT re-fire while same questionId persists", () => {
    const h = renderHelper();
    h.setItems([waitingItem("analyzer", "q1")]);
    h.setItems([waitingItem("analyzer", "q1")]); // re-render, same qid
    h.setItems([waitingItem("analyzer", "q1")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
  });

  it("switches to a different waiting agent → fires", () => {
    const h = renderHelper();
    h.setItems([waitingItem("analyzer", "q1")]);
    h.setItems([waitingItem("runner", "q2")]);
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });

  it("multi-waiting priority — earliest firstTs (first in array) wins", () => {
    const h = renderHelper();
    // deriveOutlineItems sorts by firstTs ascending; the first array entry
    // is the earliest-waiting. Two simultaneous waiting items → toast fires
    // for the first one's questionId.
    h.setItems([
      waitingItem("analyzer", "q-early", "analyzer__iter1"),
      waitingItem("runner", "q-late", "runner__iter1"),
    ]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(
      "analyzer is waiting for your answer",
      expect.anything(),
    );
  });

  it("fallback path — missing questionId degrades to key-based identity", () => {
    const h = renderHelper();
    // Engine regression case: questionId unset on the question message.
    h.setItems([waitingItem("analyzer", "", "analyzer__iter1")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Same key, empty questionId again → no re-fire.
    h.setItems([waitingItem("analyzer", "", "analyzer__iter1")]);
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Different key (e.g. iter bumped) → fires again even though qid empty.
    h.setItems([waitingItem("analyzer", "", "analyzer__iter2")]);
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });
});
```

**Step 2: Run**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/useWaitingAgentToast.test.tsx
```

Expected: 6 tests pass.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/__tests__/useWaitingAgentToast.test.tsx
git commit -m "test(outline): useWaitingAgentToast — Bug 2 fix + multi-waiting priority (Plan G)"
```

### Task 2.3: Write `useAutoFollowSelection.test.tsx`

**Files:**
- Create: `frontend/src/components/outline/__tests__/useAutoFollowSelection.test.tsx`

**Step 1: Write the test**

```tsx
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoFollowSelection } from "../useAutoFollowSelection";
import { useOutlineStore } from "../outlineStore";
import type { OutlineItem } from "../types";

function runningItem(name: string, order: number): OutlineItem {
  return {
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "running",
    activity: { kind: "running", currentStepContent: "x" },
    badges: [],
    order,
  };
}

function waitingItem(name: string, questionId: string, order: number): OutlineItem {
  return {
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
    badges: [],
    order,
  };
}

describe("useAutoFollowSelection", () => {
  beforeEach(() => {
    // Reset the outline store between tests.
    useOutlineStore.setState({ autoFollow: true, selectedKey: null });
  });

  it("autoFollow on + running item → selects it", () => {
    useOutlineStore.setState({ autoFollow: true, selectedKey: null });
    renderHook(() => useAutoFollowSelection([runningItem("analyzer", 0)]));
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });

  it("autoFollow on + waiting beats running", () => {
    useOutlineStore.setState({ autoFollow: true, selectedKey: null });
    renderHook(() =>
      useAutoFollowSelection([
        runningItem("runner", 10),
        waitingItem("analyzer", "q1", 0),
      ]),
    );
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });

  it("autoFollow on + multiple running → highest order wins", () => {
    useOutlineStore.setState({ autoFollow: true, selectedKey: null });
    renderHook(() =>
      useAutoFollowSelection([
        runningItem("early", 1),
        runningItem("late", 99),
      ]),
    );
    expect(useOutlineStore.getState().selectedKey).toBe("late__iter1");
  });

  it("autoFollow off → does not change selection", () => {
    useOutlineStore.setState({ autoFollow: false, selectedKey: "pinned__iter1" });
    renderHook(() => useAutoFollowSelection([runningItem("other", 0)]));
    expect(useOutlineStore.getState().selectedKey).toBe("pinned__iter1");
  });

  it("selection already correct → no spurious setState", () => {
    useOutlineStore.setState({ autoFollow: true, selectedKey: "analyzer__iter1" });
    const before = useOutlineStore.getState();
    renderHook(() => useAutoFollowSelection([runningItem("analyzer", 0)]));
    // selectedKey unchanged, no state mutation observed.
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });
});
```

**Step 2: Run**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/useAutoFollowSelection.test.tsx
```

Expected: 5 tests pass.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/__tests__/useAutoFollowSelection.test.tsx
git commit -m "test(outline): useAutoFollowSelection — autoFollow priority + pin behavior (Plan G)"
```

---

## Phase 3: Verification + docs

### Task 3.1: Full test suites

```bash
cd frontend && npx tsc --noEmit && npx vitest run src/components/outline
```

Expected: zero TS errors; all outline tests pass (existing 21 + new 11 = 32).

### Task 3.2: Browser smoke

```bash
cd frontend && npm run dev
```

Hard refresh (Cmd+Shift+R). On a workflow that triggers `ask_user`:

- [ ] First ask: toast appears, outline auto-selects the waiting agent (autoFollow default on).
- [ ] Answer the question.
- [ ] Second ask from the **same** agent: toast appears (Bug 2 regression check).
- [ ] Toggle autoFollow off (Pinned). Trigger a third ask from a different agent: toast still appears, but selection does not change.

### Task 3.3: Release note + CHANGELOG

**Files:**
- Create: `docs/releases/2026-06-12-outline-toast-hook-split.md`
- Modify: `docs/status/CHANGELOG.md` (prepend one-line entry)
- Modify: `docs/status/CURRENT.md` (clear task; this concludes the outline follow-up batch)

**Step 1: Write release note**

```markdown
# 2026-06-12 Outline Toast Hook Split (Plan G)

**Branch:** `main` (or feature branch if isolated)
**Plan:** `docs/plans/2026-06-12-outline-toast-hook-split.md`

Splits `useAutoFollowSelection` into two single-responsibility hooks and
fixes Bug 2 (waiting agent 二次进入 toast 漏发) as part of the same change.

## Changes

- **Bug 2 fix**: toast edge-trigger now keyed on `questionId` (with `key`-
  based fallback when engine omits `questionId`). Two consecutive asks by the
  same agent both fire toasts.
- **Arch 1 fix**: split into `useWaitingAgentToast` (toast only, ignores
  `autoFollow`) and `useAutoFollowSelection` (selection only). `AgentOutline`
  wires both.
- **Test coverage**: 11 new tests covering hook behaviors that previously had
  zero coverage (Bug 2 regression case, multi-waiting priority, fallback path,
  autoFollow on/off matrix).

## Deviations from plan

(none expected; if fallback path triggered during manual smoke, note it here
and file a follow-up to harden the engine `questionId` contract)

## Verification

- `npx tsc --noEmit` — zero errors
- `npx vitest run src/components/outline` — 32 tests pass
- Manual smoke: same-agent double-ask → both toasts fire (Bug 2 fixed)
```

**Step 2: Prepend CHANGELOG entry**

```markdown
- **2026-06-12** — **Outline Toast Hook Split (Plan G)**：拆 `useAutoFollowSelection` 为 `useWaitingAgentToast` + `useAutoFollowSelection`，toast 边沿触发改用 `questionId`，修复同一 agent 二次 ask 时漏 toast 的 Bug 2。
  → [详情](../releases/2026-06-12-outline-toast-hook-split.md)
```

**Step 3: Update CURRENT.md**

Move this batch into CHANGELOG; reset CURRENT.md to next focus. If no further
outline follow-ups pending, next focus = "browser手测 outline" (option A from
the original candidate list) or whatever the user picks next.

**Step 4: Commit**

```bash
git add docs/releases/2026-06-12-outline-toast-hook-split.md \
        docs/status/CHANGELOG.md docs/status/CURRENT.md
git commit -m "docs: Plan G complete — outline toast hook split + Bug 2 fix"
```

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| `@testing-library/react` not installed | 🟡 Medium | Task 2.1 checks first; fallback to logic-only `renderHook` from react-test-renderer if blocked. |
| Engine omits `questionId` on question messages | 🟢 Low | Fallback path `__no_qid__${key}` preserves current behavior. Test covers it. |
| Hook ordering in `AgentOutline` matters (toast vs select) | 🟢 Low | Both hooks read the same `items`; neither depends on the other's effects. Order is documentary only. |
| `useOutlineStore.setState` in tests pollutes other suites | 🟡 Medium | `beforeEach` reset in `useAutoFollowSelection.test.tsx`. zustand stores are singletons; if tests outside outline also read this store, they must not run in parallel with these tests. |
| React batches the "answer → re-ask" transition into one commit | 🟢 Low | questionId identity is robust to batching (Decision 2). |

---

## Estimate

- Phase 1 (split + wire + smoke): 20 min
- Phase 2 (11 tests): 20 min
- Phase 3 (verify + docs): 10 min

**Total: ~50 min.** Single session, no need to split.

---

## Execution Order Rationale

Phase 1 lands the production code change. Task 1.4 (manual smoke) sits between
Phase 1 and Phase 2 deliberately: if Bug 2's fix is broken, we want to know
before writing tests that pin the broken behavior.

Phase 2 tests use `@testing-library/react`'s `renderHook`, which is the
lightest-weight way to test a hook in isolation. If the project doesn't have
the dep installed, Task 2.1 handles the install — flagged as a Risk because
adding a dev dep is the only step in this plan that touches `package.json`.

Phase 3 follows the CLAUDE.md status-doc flow exactly: release note →
CHANGELOG index → CURRENT.md reset.
