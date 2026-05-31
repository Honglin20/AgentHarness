# Fix Context Architecture + Remove Legacy Path

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 4 bugs in Context Architecture, remove legacy WS/hooks from the Context path, and verify end-to-end via web UI.

**Architecture:** WorkflowCenterPanel manages WS (stable parent). Events route via eventRouter to per-workflow scoped stores. ScopedCenterPanel reads only from scoped stores and WSMethodContext. Replay mode keeps legacy CenterPanel (read-only, no stacking risk). Global stores (viewStore, batchStore) remain for shared UI state.

**Tech Stack:** React Context, Zustand vanilla stores, WebSocket, Next.js 14

---

## Bug Summary

| # | Bug | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | ScopedCenterPanel creates duplicate WS via legacy `useWorkflowEvents` | Mixed legacy/context imports | Replace with WSMethodContext |
| 2 | WorkflowScope renders children without Provider when `effectiveWorkflowId=null` | WorkflowScope computes its own active workflow independently | Move batch logic to WorkflowCenterPanel; WorkflowScope just uses passed `workflowId` |
| 3 | `window.__wsMethods` global for DI | No React context for WS methods | Create real React context |
| 4 | `window.__useContextArchitecture` flag | Implicit global toggle | Remove; Context architecture is always active for live workflows |

---

## Files Modified

| File | Action |
|------|--------|
| `frontend/src/contexts/workflow-context/WorkflowScope.tsx` | **REWRITE** — WSMethodContext as real React context, simplify WorkflowScope |
| `frontend/src/contexts/workflow-context/useWorkflowEvents.ts` | **MODIFY** — read WS from React context instead of window global |
| `frontend/src/components/layout/WorkflowCenterPanel.tsx` | **MODIFY** — fix effectiveWorkflowId, use WSMethodContext |
| `frontend/src/components/layout/ScopedCenterPanel.tsx` | **MODIFY** — remove legacy useWorkflowEvents, use WSMethodContext |
| `frontend/src/hooks/useWorkflowEvents.ts` | **MODIFY** — remove window.__useContextArchitecture check |
| `frontend/src/contexts/workflow-context/index.ts` | **MODIFY** — update exports |

**Not modified (intentionally):**
- `CenterPanel.tsx` — kept for replay mode (read-only, no stacking risk)
- Sidebar, diagnostics, header — use global stores for shared UI state, correct behavior
- `@/stores/*` — global stores stay; scoped stores are the per-workflow isolation layer

---

### Task 1: Create WSMethodContext in WorkflowScope.tsx

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx`

**Why:** Replace `window.__wsMethods` global with a proper React context. This is the foundation for Tasks 2-4.

**Step 1: Add WSMethodContext**

At the top of `WorkflowScope.tsx` (after imports), add:

```typescript
import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";

/**
 * WSMethodContext — React context for WebSocket send methods.
 *
 * Set by WorkflowCenterPanel (stable parent that owns the WS).
 * Read by ScopedCenterPanel and useScopedWorkflowEvents.
 */
interface WSMethods {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

const WSMethodContext = createContext<WSMethods | null>(null);

export function WSMethodProvider({
  sendAnswer,
  sendStopAndRegenerate,
  children,
}: WSMethods & { children: ReactNode }) {
  const value = useMemo(
    () => ({ sendAnswer, sendStopAndRegenerate }),
    [sendAnswer, sendStopAndRegenerate],
  );
  return (
    <WSMethodContext.Provider value={value}>
      {children}
    </WSMethodContext.Provider>
  );
}

export function useWSMethods(): WSMethods {
  const ctx = useContext(WSMethodContext);
  if (!ctx) {
    throw new Error(
      "useWSMethods must be used within WSMethodProvider. " +
      "Make sure WorkflowCenterPanel wraps the tree with WSMethodProvider."
    );
  }
  return ctx;
}
```

**Step 2: Remove the old `WSMethodProvider` and `getWSMethods`**

Delete the old `WSMethodProvider` function (lines 84-102 in current file) and `getWSMethods` function (lines 104-109). These used `window.__wsMethods`.

**Step 3: Simplify `WorkflowScopeInner`**

Remove `WSMethodProvider` from inside `WorkflowScopeInner` — it's now provided by `WorkflowCenterPanel`. Remove `window.__useContextArchitecture` flag. The inner component just renders children:

```typescript
function WorkflowScopeInner({ children }: { children: ReactNode }) {
  // No-op: WS methods come from WSMethodProvider in WorkflowCenterPanel
  return <>{children}</>;
}
```

**Step 4: Simplify `WorkflowScope`**

Remove batch logic from `WorkflowScope`. It receives `workflowId` and renders Provider:

```typescript
interface WorkflowScopeProps {
  workflowId: string | null;
  children: ReactNode;
}

export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  if (!stores) return <>{children}</>;

  return (
    <WorkflowProvider
      workflowId={workflowId}
      stores={stores}
      setActiveWorkflowId={setActiveWorkflowId}
    >
      <WorkflowScopeInner>
        {children}
      </WorkflowScopeInner>
    </WorkflowProvider>
  );
}
```

Note: `batchId` prop removed. Batch logic moves to `WorkflowCenterPanel` (Task 3).

**Step 5: Commit**

```
feat: replace window globals with WSMethodContext, simplify WorkflowScope
```

---

### Task 2: Fix useScopedWorkflowEvents — read from React context

**Files:**
- Modify: `frontend/src/contexts/workflow-context/useWorkflowEvents.ts`

**Step 1: Replace `getWSMethods()` with `useWSMethods()`**

```typescript
import { useCallback } from "react";
import { useConversationActions, useChatActions } from "./hooks";
import { useWorkflowContext } from "./WorkflowContext";
import { useWSMethods } from "./WorkflowScope";

export interface ScopedWorkflowEventsReturn {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

export function useScopedWorkflowEvents(): ScopedWorkflowEventsReturn {
  const ws = useWSMethods();
  const conversationActions = useConversationActions();
  const chatActions = useChatActions();

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.sendAnswer(questionId, answer);
      chatActions.addUserAnswer(questionId, answer);
      conversationActions.addUserMessage(answer);
      conversationActions.clearPendingQuestion(questionId);
    },
    [ws, chatActions, conversationActions],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      ws.sendStopAndRegenerate(agentName, partialOutput, userGuidance);
      conversationActions.interruptAgentMessage(agentName);
    },
    [ws, conversationActions],
  );

  return { sendAnswer, sendStopAndRegenerate };
}

export function setActiveWorkflowId(id: string | null): void {
  const { getWorkflowManager } = require("./WorkflowManager");
  getWorkflowManager().setActiveWorkflowId(id);
}
```

**Step 2: Commit**

```
fix: useScopedWorkflowEvents reads WS methods from React context
```

---

### Task 3: Fix WorkflowCenterPanel — unify effectiveWorkflowId

**Files:**
- Modify: `frontend/src/components/layout/WorkflowCenterPanel.tsx`

**Why:** The root cause of "useWorkflowContext must be used within WorkflowProvider" is that WorkflowCenterPanel and WorkflowScope compute different "active workflow" values. Fix: WorkflowCenterPanel owns the decision, WorkflowScope just uses the passed value.

**Step 1: Fix `useActiveWorkflowId`**

```typescript
function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Replay mode: handled by legacy CenterPanel
  if (activeView.type === "replay") {
    return null; // Will trigger legacy path
  }

  // Batch mode: only enter Context path when a run is explicitly selected
  if (activeBatchId) {
    return selectedRunId;
  }

  // Normal mode: use the global workflowId
  return workflowId;
}
```

**Step 2: Rewrite WorkflowCenterPanel**

```typescript
export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);

  // WebSocket managed at this stable level — survives workflow switches
  const wsMethods = useWorkflowWS(workflowId);

  // Replay mode or no active workflow: use legacy CenterPanel
  if (activeView.type === "replay" || !workflowId) {
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  // Context architecture: WS + scoped stores
  return (
    <WSMethodProvider
      sendAnswer={wsMethods.sendAnswer}
      sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
    >
      <WorkflowScope workflowId={workflowId}>
        <ScopedCenterPanel activeBenchmark={activeBenchmark} />
      </WorkflowScope>
    </WSMethodProvider>
  );
}
```

Key changes:
- `useActiveWorkflowId` returns `null` for batch mode without selected run → legacy path
- `useActiveWorkflowId` returns `null` for replay → legacy path
- Only returns a truthy workflowId when Context path should be used
- `WorkflowScope` receives a guaranteed non-null `workflowId` (since we checked `!workflowId`)
- No more `batchId` prop on `WorkflowScope`
- `activeView.type === "replay"` check removed from `useWorkflowWS` call (handled by null workflowId)

**Step 3: Update imports**

Remove `useBatchStore` import (no longer used directly in the component; it's in the hook). Remove `activeBatchId` from the component. Add nothing new.

The final imports for the component:

```typescript
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowScope, WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
import { useWorkflowWS } from "@/contexts/workflow-context/useWorkflowWS";
import { ScopedCenterPanel } from "./ScopedCenterPanel";
```

**Step 4: Commit**

```
fix: unify effectiveWorkflowId computation in WorkflowCenterPanel
```

---

### Task 4: Fix ScopedCenterPanel — remove legacy useWorkflowEvents

**Files:**
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx`

**Why:** ScopedCenterPanel imports legacy `useWorkflowEvents` from `@/hooks/useWorkflowEvents`, which creates a **second WebSocket** on top of the one created by `useWorkflowWS` in WorkflowCenterPanel. This causes duplicate event processing and potential stacking.

**Step 1: Remove legacy import**

Delete this line:
```typescript
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
```

**Step 2: Replace `useWorkflowEvents` call with `useWSMethods`**

Add import:
```typescript
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
```

Replace the `useWorkflowEvents` call (around line 104):
```typescript
// OLD:
const { sendAnswer, sendStopAndRegenerate } = useWorkflowEvents(
    batchRunning ? null : workflowId,
);

// NEW:
const { sendAnswer, sendStopAndRegenerate } = useWSMethods();
```

This reads from the WSMethodContext provided by WorkflowCenterPanel. No new WebSocket is created.

**Step 3: Remove `chatStore` import if only used by legacy hook**

Check if `useChatStore` is still needed. If `useWorkflowEvents` was the only consumer, remove:
```typescript
import { useChatStore } from "@/stores/chatStore";
```

The `chatActions.addUserAnswer` etc. are handled by `useScopedWorkflowEvents` inside `WSMethodProvider`.

Actually, looking at the code: `useChatStore` is NOT imported in ScopedCenterPanel. The legacy `useWorkflowEvents` hook internally uses `useChatStore`, but ScopedCenterPanel doesn't import it directly. So no change needed here.

**Step 4: Commit**

```
fix: remove legacy useWorkflowEvents from ScopedCenterPanel, use WSMethodContext
```

---

### Task 5: Clean up legacy useWorkflowEvents.ts — remove context architecture flag

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts`

**Step 1: Remove `window.__useContextArchitecture` check**

In the `setActiveWorkflowId` function, remove the context-mode branch:

```typescript
// OLD:
export function setActiveWorkflowId(id: string | null) {
  const currentId = useWorkflowStore.getState().activeWorkflowId;
  const isInContextMode = typeof window !== "undefined" && (window as unknown as { __useContextArchitecture?: boolean }).__useContextArchitecture;

  if (isInContextMode) {
    useWorkflowStore.getState().setActiveWorkflowId(id);
    useWorkflowStore.getState().setActiveWid(id);
    return;
  }
  // ... legacy logic
}

// NEW: (just the legacy path — only called when Context architecture is NOT active)
export function setActiveWorkflowId(id: string | null) {
  const currentId = useWorkflowStore.getState().activeWorkflowId;

  if (currentId && currentId !== id) {
    useConversationStore.getState().saveToCache(currentId);
    useOutputStore.getState().saveToCache(currentId);
  }

  useWorkflowStore.getState().setActiveWorkflowId(id);

  if (id !== currentId) {
    useWorkflowStore.getState().setActiveWid(id);
  }

  if (id && id !== currentId) {
    // ... rest of restore logic unchanged
  }
}
```

This function is only called from `CenterPanel.tsx` (legacy path, used for replay mode). When Context architecture is active, `WorkflowManager.setActiveWorkflowId` is used instead.

**Step 2: Commit**

```
cleanup: remove window.__useContextArchitecture flag from legacy hook
```

---

### Task 6: Update index.ts exports

**Files:**
- Modify: `frontend/src/contexts/workflow-context/index.ts`

**Step 1: Update exports**

Replace the old `WSMethodProvider` and `getWSMethods` exports:

```typescript
// OLD:
export { WorkflowScope, WSMethodProvider, getWSMethods } from "./WorkflowScope";

// NEW:
export { WorkflowScope, WSMethodProvider, useWSMethods } from "./WorkflowScope";
```

Verify `useWSMethods` is exported but NOT `getWSMethods`.

**Step 2: Commit**

```
chore: update context exports for WSMethodContext
```

---

### Task 7: TypeScript check + Build

**Step 1: Run TypeScript check**

```bash
cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit
```

Expected: No errors.

If errors found, fix them before proceeding. Common issues:
- Missing import for `useWSMethods`
- Type mismatch in WorkflowScope props (removed `batchId`)
- Unused import warnings

**Step 2: Run build**

```bash
cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build
```

Expected: Clean build, no errors.

**Step 3: Commit if build output changed**

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend for context architecture fix"
```

---

### Task 8: E2E Verification — Single Workflow

**Precondition:** Backend running (`python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`).

**Test 1: Start a single workflow**

1. Open http://localhost:3000
2. Select a workflow template (e.g., code_review)
3. Enter a task and start
4. Verify: conversation messages appear in real-time
5. Verify: DAG panel shows node status updates
6. Verify: no errors in browser console (F12)
7. Wait for completion
8. Verify: status changes to "completed", chart data appears in Results/Analysis tabs

**Pass criteria:**
- No "useWorkflowContext must be used within WorkflowProvider" error
- No "useWSMethods must be used within WSMethodProvider" error
- Live streaming works (text deltas appear progressively)
- Tool calls and results display correctly
- Completion shows correct output

---

### Task 9: E2E Verification — Concurrent Workflows

**Test 2: Start two workflows simultaneously**

1. Start workflow A (e.g., code_review with task "Review this code")
2. Immediately start workflow B (same or different template)
3. Switch to workflow A in sidebar — verify A's conversation only
4. Switch to workflow B — verify B's conversation only (no A's messages)
5. Switch back to A — verify A's messages are intact
6. Verify: no message stacking or mixing
7. Verify: no WS errors in console

**Test 3: Batch mode**

1. Create a benchmark with 2-3 tasks
2. Run the benchmark
3. While running, click on individual runs in the batch runner
4. Verify: each run shows its own conversation
5. Verify: switching between runs doesn't stack messages
6. Verify: batch progress table updates correctly

**Test 4: Replay mode**

1. Go to sidebar run history
2. Click on a completed run to replay
3. Verify: conversation and charts display correctly
4. Verify: "REPLAY" badge shows
5. Verify: no errors

**Pass criteria for all tests:**
- Zero console errors
- No message stacking
- Correct state on every switch
- No WS disconnection errors
