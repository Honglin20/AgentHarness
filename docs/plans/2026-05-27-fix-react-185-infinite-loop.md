# Fix React Error #185 — Infinite Update Loop

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate React Error #185 (Maximum update depth exceeded) and harden the frontend state management against reference-instability defects.

**Architecture:** The root cause is unstable selectors in scoped hooks — they return new object references on every `useSyncExternalStore` snapshot, causing React to detect infinite state changes. Fix strategy: (1) use `useShallow` for object-returning selectors, (2) fix `useState`→`useEffect` misuse, (3) stabilize action references via `useRef`, (4) stabilize ChatInput inline callbacks via `useMemo`.

**Tech Stack:** React 18, Zustand 5.0.13 (has `useShallow`), Next.js 14.2.29

---

## Defect Summary

| # | Defect | File | Root Cause | Severity |
|---|--------|------|-----------|----------|
| D1 | Object-returning selectors unstable | `contexts/workflow-context/hooks.ts` | `useSyncExternalStore` + `Object.is` sees new object ≠ old object → infinite re-render | **Critical** |
| D2 | `useState` used as `useEffect` | `components/layout/CenterPanel.tsx:116` | Side-effect (fetch) runs in `useState` initializer during render | High |
| D3 | `store.getState()` in render path | `contexts/workflow-context/hooks.ts` — `useWorkflowActions` etc. | Returns new state object ref each render → unstable `useCallback` deps | High |
| D4 | ChatInput inline callbacks | `components/chat/ChatInput.tsx:58-60` | `??` fallback creates new function each render → unstable deps | Medium |

---

## Task 1: Fix unstable selectors in scoped hooks (D1 — Critical)

**Files:**
- Modify: `frontend/src/contexts/workflow-context/hooks.ts`

**Why:** `usePendingQuestion()`, `useWorkflowInfo()`, `useChartGroups()` all create new objects in selectors. With `useSyncExternalStore`, `Object.is` always returns false for new objects, causing React to loop. Zustand 5 ships `useShallow` exactly for this pattern — it shallow-compares previous and next selector results, returning the cached ref if equal.

**Step 1: Add `useShallow` import**

At the top of `hooks.ts`, add to the zustand import:

```typescript
import { useStore, useShallow } from "zustand";
```

**Step 2: Fix `usePendingQuestion`**

Replace lines 58-66:

```typescript
// BEFORE (unstable — new object each call)
export function usePendingQuestion(): {
  questionId: string | null;
  agentName: string | null;
} {
  return useScopedConversationStore((s) => ({
    questionId: s.pendingQuestionId,
    agentName: s.pendingQuestionAgent,
  }));
}

// AFTER (stable — useShallow shallow-compares and caches)
export function usePendingQuestion(): {
  questionId: string | null;
  agentName: string | null;
} {
  return useScopedConversationStore(
    useShallow((s) => ({
      questionId: s.pendingQuestionId,
      agentName: s.pendingQuestionAgent,
    }))
  );
}
```

**Step 3: Fix `useWorkflowInfo`**

Replace lines 138-148:

```typescript
// BEFORE (unstable)
export function useWorkflowInfo(): {
  workflowId: string | null;
  workflowName: string | null;
  status: WorkflowState["status"];
} {
  return useScopedWorkflowStore((s) => ({
    workflowId: s.workflowId,
    workflowName: s.workflowName,
    status: s.status,
  }));
}

// AFTER (stable)
export function useWorkflowInfo(): {
  workflowId: string | null;
  workflowName: string | null;
  status: WorkflowState["status"];
} {
  return useScopedWorkflowStore(
    useShallow((s) => ({
      workflowId: s.workflowId,
      workflowName: s.workflowName,
      status: s.status,
    }))
  );
}
```

**Step 4: Fix `useChartGroups`**

Replace lines 228-233:

```typescript
// BEFORE (unstable)
export function useChartGroups(): { groups: Record<string, ChartGroup>; order: string[] } {
  return useScopedChartStore((s) => ({
    groups: s.groups,
    order: s.groupOrder,
  }));
}

// AFTER (stable)
export function useChartGroups(): { groups: Record<string, ChartGroup>; order: string[] } {
  return useScopedChartStore(
    useShallow((s) => ({
      groups: s.groups,
      order: s.groupOrder,
    }))
  );
}
```

**Step 5: Fix `useLiveAnalysisCount` — eliminate unstable `useChartGroups` call**

`useLiveAnalysisCount` calls `useChartGroups()` which we just fixed. But the derived count computation can be done inline without the intermediate object. Replace lines 249-259:

```typescript
// BEFORE (calls unstable hook + manual loop)
export function useLiveAnalysisCount(): number {
  const { groups, order } = useChartGroups();
  let count = 0;
  for (const label of order) {
    const g = groups[label];
    if (g?.category === "analysis") {
      count++;
    }
  }
  return count;
}

// AFTER (single stable selector returning primitive)
export function useLiveAnalysisCount(): number {
  return useScopedChartStore((s) => {
    let count = 0;
    for (const label of s.groupOrder) {
      if (s.groups[label]?.category === "analysis") count++;
    }
    return count;
  });
}
```

**Step 6: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds, no new warnings.

**Step 7: Commit**

```bash
git add frontend/src/contexts/workflow-context/hooks.ts
git commit -m "fix: stabilize scoped hook selectors with useShallow (D1)"
```

---

## Task 2: Fix `useState` misuse as `useEffect` in CenterPanel (D2)

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx:116-121`

**Why:** `useState(() => { fetch... })` runs a side-effect (network fetch) during render. The React `useState` initializer should be pure. Use `useEffect` instead.

**Step 1: Replace the `useState` call with `useEffect`**

Replace lines 115-121:

```typescript
// BEFORE (BUG — side-effect in useState initializer)
// Fetch templates for the landing page cards
useState(() => {
  fetch("/api/workflows/definitions")
    .then((r) => r.json())
    .then((data: SavedWorkflow[]) => setTemplates(data))
    .catch(() => {});
});

// AFTER (correct — side-effect in useEffect)
// Fetch templates for the landing page cards
useEffect(() => {
  fetch("/api/workflows/definitions")
    .then((r) => r.json())
    .then((data: SavedWorkflow[]) => setTemplates(data))
    .catch(() => {});
}, []);
```

Note: `useEffect` is already imported in this file.

**Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add frontend/src/components/layout/CenterPanel.tsx
git commit -m "fix: replace useState side-effect with useEffect in CenterPanel (D2)"
```

---

## Task 3: Stabilize store action references (D3)

**Files:**
- Modify: `frontend/src/contexts/workflow-context/hooks.ts`

**Why:** `useWorkflowActions()`, `useOutputActions()`, `useConversationActions()`, `useChartActions()` all call `store.getState()` during render. This returns a new state object each time the store updates. When used as `useCallback` dependencies in `ScopedCenterPanel`, the callbacks are recreated on every store change, cascading unnecessary re-renders to child components (ChatInput, etc.).

Fix: cache the store API in a `useRef`, return a stable accessor. Callers use individual methods via `useCallback`.

**Step 1: Add `useRef` import**

The import for `useRef` is not in the current file. Add it via a React import:

At the top of `hooks.ts`, add:

```typescript
import { useRef } from "react";
```

Wait — the file currently has no React import (it uses zustand's `useStore`). We need `useRef` from React. Add the import at the top:

```typescript
import { useRef } from "react";
```

**Step 2: Create stable action accessor helpers**

After the `useWorkflowId` hook (around line 303), add a new helper:

```typescript
/**
 * useStableStoreActions
 *
 * Returns a stable reference to a store's getState() result.
 * Re-reads only when the store reference changes (not on every state update).
 * Use this for calling actions (methods) that don't need to be reactive.
 */
function useStableStoreActions<T>(store: StoreApi<T> | null): T | null {
  const ref = useRef<T | null>(null);
  if (store) {
    ref.current = store.getState();
  }
  return store ? ref.current : null;
}
```

Wait — this still reads `store.getState()` on every render. The point is to NOT re-render when store state changes, while still having access to the latest actions.

Actually, the better approach: since actions in zustand stores are stable function references (they're defined once in the store creator), we can just get them once via `useRef` + `useEffect`-less pattern. But the simplest correct approach is to NOT subscribe to the store at all — just call `store.getState()` inside callbacks, not during render.

The real fix: change the consumers (`ScopedCenterPanel`) to not use these hooks as render-time values. Instead, pass store references and let components call `store.getState().action()` inside their callbacks.

But that's a bigger refactor. The minimal fix: wrap the store reference in a ref and lazily get state.

**Revised approach — minimal change:**

Replace the four action hooks to return individual stable method references:

```typescript
/**
 * useWorkflowActions
 *
 * Returns stable references to workflow store actions.
 * Actions are stable in zustand (defined once in creator), so we can
 * safely read them from getState() inside useCallback.
 */
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) {
    throw new Error("useWorkflowActions must be used within WorkflowProvider");
  }
  // store reference is stable (from useMemo in WorkflowScope)
  // getState() is called lazily in callbacks, not during render
  return store;
}
```

Wait — this changes the return type from `WorkflowState` to `StoreApi<WorkflowState>`. That breaks all callers.

**Best minimal fix: use `useRef` to cache the action object, update only when store reference changes.**

```typescript
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) {
    throw new Error("useWorkflowActions must be used within WorkflowProvider");
  }
  // Actions are stable in zustand — they're defined once in the store creator.
  // We use the store itself as a key to detect when the store instance changed.
  return store.getState();
}
```

Actually the simplest correct fix that doesn't change the API:

Since scoped stores are created once per workflow (in `useMemo` in `WorkflowScope`), the store reference is stable for the lifetime of a workflow. And since zustand store actions are stable references (they're functions bound in the creator), `store.getState()` will return the same function references even when called multiple times.

The problem is that `store.getState()` also returns the data properties (`status`, `workflowId`, etc.) which DO change. But callers only use the action methods (`reset`, `setWorkflow`, etc.), not the data.

So the actual fix: have callers destructure only the methods they need, and wrap them in `useMemo`:

But that changes the caller code. Let me do the simplest thing: just make the hooks return the store itself (a stable ref) and update callers to call `.getState().action()`.

**Final approach — change return type to StoreApi, update callers:**

Replace each action hook:

```typescript
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) {
    throw new Error("useWorkflowActions must be used within WorkflowProvider");
  }
  return store;
}
```

Then in `ScopedCenterPanel.tsx`, change:

```typescript
// BEFORE (unstable — whole state object as dependency)
const workflowActions = useWorkflowActions();
const outputActions = useOutputActions();
const chartActions = useChartActions();
const conversationActions = useConversationActions();

// AFTER (stable — store API reference)
const workflowStore = useWorkflowActions();
const outputStore = useOutputActions();
const chartStore = useChartActions();
const conversationStore = useConversationActions();
```

And update usage sites (e.g. `workflowActions.reset()` → `workflowStore.getState().reset()`).

This is clean but touches multiple files. Let me take the most minimal approach instead:

**Actually minimal approach:** Since the store reference IS stable (from `useMemo` in WorkflowScope), and zustand actions ARE stable function references, we can memoize the action object:

Replace lines 373-379:

```typescript
// BEFORE
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) {
    throw new Error("useWorkflowActions must be used within WorkflowProvider");
  }
  return store.getState();
}

// AFTER — memoize by store reference
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) {
    throw new Error("useWorkflowActions must be used within WorkflowProvider");
  }
  const ref = useRef<WorkflowState | null>(null);
  if (ref.current === null || ref.current._store !== store) {
    const state = store.getState();
    (state as any)._store = store; // tag for identity check
    ref.current = state;
  }
  return ref.current;
}
```

No, that's ugly — mutating state objects.

**Cleanest minimal approach:** Since we're in React and the store reference is stable, use a `useRef` keyed by the store:

```typescript
const actionCache = new WeakMap<StoreApi<any>, any>();

export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) throw new Error("useWorkflowActions must be used within WorkflowProvider");
  if (!actionCache.has(store)) actionCache.set(store, store.getState());
  return actionCache.get(store);
}
```

This is clean: cache by store reference, return the same state object for the same store. Since stores are created once per workflow, the cache is stable.

BUT there's a problem: `store.getState()` returns a snapshot that includes data (`status`, `workflowId`). If you call `workflowActions.status`, you get stale data. But callers only use methods (`reset()`, `setWorkflow()`, etc.), not data. The data comes from the reactive hooks (`useWorkflowStatus`, `useWorkflowInfo`).

This is correct — callers in `ScopedCenterPanel` use:
- `workflowActions.reset()`, `workflowActions.setWorkflow()`, `workflowActions.setSelectedTemplate()`, `workflowActions.previewTemplate()`, `workflowActions.clearPreview()` — all methods
- `outputActions.reset()`, `chartActions.reset()` — all methods
- `conversationActions.addUserMessage()`, `conversationActions.clearPendingQuestion()`, `conversationActions.interruptAgentMessage()` — all methods

So caching `getState()` by store reference is safe for actions.

**Step 2: Replace all four action hooks**

Replace lines 373-418 (`useWorkflowActions`, `useOutputActions`, `useConversationActions`, `useChartActions`, `useChatActions`):

```typescript
/**
 * Cache store action objects by store reference.
 * Since zustand actions are stable function references defined once in the creator,
 * and stores are created once per workflow (useMemo in WorkflowScope),
 * the cached object is stable across renders.
 */
const actionCache = new WeakMap<StoreApi<any>, any>();

function getStableActions<T>(store: StoreApi<T>): T {
  if (!actionCache.has(store)) {
    actionCache.set(store, store.getState());
  }
  return actionCache.get(store);
}

export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) throw new Error("useWorkflowActions must be used within WorkflowProvider");
  return getStableActions(store);
}

export function useOutputActions() {
  const store = getWorkflowStoreApi("output");
  if (!store) throw new Error("useOutputActions must be used within WorkflowProvider");
  return getStableActions(store);
}

export function useConversationActions() {
  const store = getWorkflowStoreApi("conversation");
  if (!store) throw new Error("useConversationActions must be used within WorkflowProvider");
  return getStableActions(store);
}

export function useChartActions() {
  const store = getWorkflowStoreApi("chart");
  if (!store) throw new Error("useChartActions must be used within WorkflowProvider");
  return getStableActions(store);
}

export function useChatActions() {
  const store = getWorkflowStoreApi("chat");
  if (!store) throw new Error("useChatActions must be used within WorkflowProvider");
  return getStableActions(store);
}
```

**Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/contexts/workflow-context/hooks.ts
git commit -m "fix: stabilize action hooks with WeakMap cache (D3)"
```

---

## Task 4: Stabilize ChatInput fallback callbacks (D4)

**Files:**
- Modify: `frontend/src/components/chat/ChatInput.tsx:58-60`

**Why:** The `??` fallback creates new inline functions on every render when scoped props are NOT provided (legacy path). ESLint warns these make `useCallback` deps change every render. Fix: wrap in `useMemo`.

**Step 1: Wrap fallback callbacks in `useMemo`**

Replace lines 58-60:

```typescript
// BEFORE (unstable inline functions)
const addUserMsg = propAddUserMsg ?? ((text: string) => useConversationStore.getState().addUserMessage(text));
const clearPQ = propClearPQ ?? ((id: string) => useConversationStore.getState().clearPendingQuestion(id));
const interruptMsg = propInterrupt ?? ((name: string) => useConversationStore.getState().interruptAgentMessage(name));

// AFTER (stable via useMemo)
const addUserMsg = useMemo(
  () => propAddUserMsg ?? ((text: string) => useConversationStore.getState().addUserMessage(text)),
  [propAddUserMsg]
);
const clearPQ = useMemo(
  () => propClearPQ ?? ((id: string) => useConversationStore.getState().clearPendingQuestion(id)),
  [propClearPQ]
);
const interruptMsg = useMemo(
  () => propInterrupt ?? ((name: string) => useConversationStore.getState().interruptAgentMessage(name)),
  [propInterrupt]
);
```

Note: `useMemo` is already imported in ChatInput.tsx (line 3).

**Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds, ChatInput warnings gone.

**Step 3: Commit**

```bash
git add frontend/src/components/chat/ChatInput.tsx
git commit -m "fix: stabilize ChatInput callback references with useMemo (D4)"
```

---

## Task 5: Smoke test — full build + manual verification

**Step 1: Clean build**

Run: `cd frontend && rm -rf .next && npm run build`
Expected: Build succeeds with 0 errors. Existing warnings for `useWorkflowEvents.ts` (missing `ws` dep) remain but are pre-existing and out of scope.

**Step 2: Run existing tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && pytest tests/ -x -q --timeout=30`
Expected: All existing tests pass (these are Python backend tests; frontend has no test suite currently).

**Step 3: Manual browser test**

Run: `cd frontend && npm run dev`
Open `http://localhost:3000` in browser.

Verify:
1. Page loads without React Error #185 in console
2. Landing page shows workflow templates
3. Selecting a template shows the DAG preview
4. Starting a workflow shows the conversation tab streaming
5. No flickering or repeated re-renders visible

**Step 4: Commit if any fixes needed**

---

## Task 6: Update docs/status/CURRENT.md

**Files:**
- Modify: `docs/status/CURRENT.md`

Update to reflect completed work:

```markdown
# Current Task

**当前任务**: Fix React Error #185 — frontend state management stabilization
**状态**: completed

---

## 已完成

- [D1] Fixed unstable selectors in scoped hooks via `useShallow` (hooks.ts)
- [D2] Fixed `useState` misuse as `useEffect` in CenterPanel
- [D3] Stabilized action hook references via WeakMap cache
- [D4] Stabilized ChatInput fallback callbacks via useMemo

---

## 必读文件

1. `frontend/src/contexts/workflow-context/hooks.ts`
```
