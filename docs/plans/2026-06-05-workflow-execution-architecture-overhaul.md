# Workflow Execution Architecture Overhaul — Eliminate Legacy Path

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the dual event routing system (legacy global stores + scoped stores) by removing the legacy path entirely. All events flow through one pipe: WebSocket → eventRouter → scoped stores → components. This fixes data cross-contamination between parallel workflows, history showing only one agent, ask_user stale state after refresh, and benchmark state loss.

**Architecture:** Single event pipeline. `WorkflowCenterPanel` owns WebSocket lifecycle. All events dispatched through `eventRouter` → `routeEvent` → per-workflow scoped stores (via `WorkflowManager`). Landing page, live, replay, and benchmark modes all render through `ScopedCenterPanel` which reads only from scoped stores. On page refresh, REST fetch pre-populates scoped stores before WebSocket reconnects.

**Tech Stack:** React 18, Zustand (scoped vanilla stores), Next.js 14, WebSocket, TypeScript

---

## Root Cause → Fix Mapping

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Parallel workflows output crosses | Legacy `_routeToUIStores()` writes all events to same global stores | Delete legacy path; all events through scoped stores |
| History shows only one agent | `RunHistoryList` calls legacy `setWorkflow()` (global) but UI reads scoped | Migrate to `WorkflowManager.setActiveWorkflowId()` |
| ask_user stale after refresh | Scoped stores rebuilt empty; no REST recovery before WS reconnect | Pre-populate from REST on mount, then WS resumes |
| Benchmark state lost | `batchStore` is memory-only, no URL persistence | Persist `activeBatchId`/`selectedRunId` to URL params |
| Double WebSocket | Both `useWorkflowWS` and legacy `useWorkflowEvents` open connections | Remove legacy WS; single WS in `WorkflowCenterPanel` |

---

## Files Modified

| File | Action | Tasks |
|------|--------|-------|
| `frontend/src/hooks/useWorkflowEvents.ts` | DELETE | 7 |
| `frontend/src/components/layout/CenterPanel.tsx` | DELETE | 7 |
| `frontend/src/components/layout/WorkflowCenterPanel.tsx` | REWRITE | 1 |
| `frontend/src/components/layout/ScopedCenterPanel.tsx` | MODIFY | 2 |
| `frontend/src/stores/viewStore.ts` | MODIFY | 3 |
| `frontend/src/components/sidebar/RunHistoryList.tsx` | MODIFY | 4 |
| `frontend/src/components/output/WorkflowLauncher.tsx` | MODIFY | 4 |
| `frontend/src/hooks/useUrlState.ts` | MODIFY | 4 |
| `frontend/src/hooks/useResetWorkflow.ts` | MODIFY | 4 |
| `frontend/src/stores/userStore.ts` | MODIFY | 4 |
| `frontend/src/contexts/workflow-context/WorkflowManager.ts` | MODIFY | 5 |
| `frontend/src/contexts/workflow-context/index.ts` | MODIFY | 5 |
| `frontend/src/stores/batchStore.ts` | MODIFY | 6 |
| `frontend/src/contexts/workflow-context/useWorkflowWS.ts` | MODIFY | 7 |

**Not modified (intentionally):**
- All scoped components (`ScopedConversationTab`, `ScopedResultsTab`, etc.) — already read from scoped stores
- Global stores (`workflowStore`, `conversationStore`, etc.) — kept for non-scoped components (HeaderBar, Sidebar)
- Backend code — no changes needed

---

### Task 1: Rewrite WorkflowCenterPanel — Eliminate Legacy Fallback

**Files:**
- Modify: `frontend/src/components/layout/WorkflowCenterPanel.tsx`

**Why:** Currently when `workflowId === null`, it falls back to legacy `CenterPanel` (which creates a second WebSocket and writes to global stores). We need all paths to go through `ScopedCenterPanel`.

**Step 1: Rewrite WorkflowCenterPanel**

Replace the entire file content:

```typescript
"use client";

import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowScope, WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
import { useWorkflowWS } from "@/contexts/workflow-context/useWorkflowWS";
import { ConnectionStatusBar } from "@/components/layout/ConnectionStatusBar";
import { ScopedCenterPanel } from "./ScopedCenterPanel";

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  if (activeView.type === "replay") return activeView.runId;
  if (activeBatchId) return selectedRunId;
  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);
  const isReplay = activeView.type === "replay";

  // Single WebSocket — managed at stable parent level
  // null for replay (no live events needed) or when no workflow active
  const wsMethods = useWorkflowWS(isReplay ? null : workflowId);

  return (
    <WorkflowScope workflowId={workflowId}>
      {!isReplay && workflowId && (
        <ConnectionStatusBar isConnected={wsMethods.isConnected} />
      )}
      <WSMethodProvider
        sendAnswer={wsMethods.sendAnswer}
        sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
        sendGuidance={wsMethods.sendGuidance}
        sendFollowup={wsMethods.sendFollowup}
        sendStructuredAnswer={wsMethods.sendStructuredAnswer}
        sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
      >
        <ScopedCenterPanel
          activeBenchmark={activeBenchmark}
          isReplay={isReplay}
        />
      </WSMethodProvider>
    </WorkflowScope>
  );
}
```

**Important:** When `workflowId === null` (landing page), `WorkflowScope` renders `<>{children}</>` without a Provider (existing behavior at line 139 of WorkflowScope.tsx). `ScopedCenterPanel` already handles the landing/portal case. `WSMethodProvider` provides methods even when no WS is connected — the methods are no-ops in that case.

**Step 2: Update WSMethodProvider to accept all send methods**

Read `frontend/src/contexts/workflow-context/WorkflowScope.tsx` and check the `WSMethodProvider` interface. It may only accept `sendAnswer` and `sendStopAndRegenerate`. If so, expand it to accept all methods returned by `useWorkflowWS`:

```typescript
interface WSMethods {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
  sendFollowup: (agentName: string, question: string) => void;
}
```

**Step 3: Verify the build compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

Fix any type errors. Common issues:
- `WSMethodProvider` prop mismatch — ensure all methods are passed
- Missing `isConnected` on `useWorkflowWS` return when workflowId is null — it should return `false`

**Step 4: Commit**

```
refactor: WorkflowCenterPanel uses scoped architecture for all modes
```

---

### Task 2: Move Landing Page Functionality into ScopedCenterPanel

**Files:**
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx`

**Why:** `ScopedCenterPanel` currently assumes a workflow is always active. It needs to handle the landing/portal state (no workflow, template selection, DAG preview, startWorkflow). This is the functionality currently in legacy `CenterPanel`.

**Step 1: Read current ScopedCenterPanel**

Read `frontend/src/components/layout/ScopedCenterPanel.tsx` completely. Identify:
- What it currently renders for each mode (live, replay, benchmark)
- What hooks it uses from scoped stores
- Where the "no workflow" branch currently goes

**Step 2: Read current CenterPanel**

Read `frontend/src/components/layout/CenterPanel.tsx` completely. Identify the landing page logic:
- `DomainPortal` rendering (line ~336)
- `DomainWorkflowsPage` rendering
- `DomainTutorialPage` rendering
- `ApiDocPage` rendering
- `DAGPreview` rendering (idle with selectedTemplate)
- `startWorkflow` function (line ~170)
- `ChatInput` for landing page

**Step 3: Add landing page imports to ScopedCenterPanel**

Add to `ScopedCenterPanel.tsx` imports:

```typescript
import { DomainPortal } from "@/components/portal/DomainPortal";
import { DomainWorkflowsPage } from "@/components/portal/DomainWorkflowsPage";
import { DomainTutorialPage } from "@/components/portal/DomainTutorialPage";
import { ApiDocPage } from "@/components/portal/ApiDocPage";
import { DAGPreview } from "@/components/dag/DAGPreview";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { usePortalStore } from "@/stores/portalStore";
import { useSettingsStore } from "@/stores/settingsStore";
```

**Step 4: Add landing page state and logic**

Add these to the `ScopedCenterPanel` function, using scoped store hooks:

```typescript
const selectedTemplate = useSelectedTemplate();
const dag = useWorkflowDAG();
const portalView = usePortalStore((s) => s.portalView);

const isIdle = !isReplay && status === "idle" && nodeCount === 0;
const effectiveWorkflowName = workflowName ?? ((selectedTemplate as Record<string, unknown> | null)?.name as string | undefined);
```

Also add the `startWorkflow` function adapted to use scoped store actions:

```typescript
const startWorkflow = useCallback(async (template: unknown, task: string) => {
  const t = template as Record<string, unknown>;
  const agents = (t.agents as Array<Record<string, unknown>>).map((a) => ({
    name: a.name,
    after: a.after,
    ...(a.on_pass != null ? { on_pass: a.on_pass } : {}),
    ...(a.on_fail != null ? { on_fail: a.on_fail } : {}),
    ...(a.eval ? { eval: true } : {}),
  }));

  // Reset scoped stores
  outputActions.reset();
  chartActions.reset();
  workflowActions.reset();

  useViewStore.getState().showLive();

  try {
    const r = await fetchWithAuth("/api/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: t.name,
        workflow: t.name,
        agents,
        inputs: { task },
        work_dir: useSettingsStore.getState().defaultWorkDir.trim() || undefined,
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();

    // Activate the workflow — WorkflowManager will create scoped stores
    getWorkflowManager().setActiveWorkflowId(data.workflow_id);
    workflowActions.setWorkflow(data.workflow_id, t.name as string, data.dag);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("Failed to start workflow:", msg);
  }
}, [outputActions, chartActions, workflowActions]);
```

**Step 5: Add landing page rendering branches**

Before the existing tab rendering logic, add:

```tsx
// Landing page — Domain Portal
if (isIdle && !selectedTemplate) {
  if (portalView === "workflows") return <DomainWorkflowsPage />;
  if (portalView === "tutorial") return <DomainTutorialPage />;
  if (portalView === "api-doc") return <ApiDocPage />;
  return (
    <>
      <DomainPortal />
      <div className="w-full max-w-4xl mx-auto px-4">
        <ChatInput
          startWorkflow={startWorkflow}
          alwaysVisible
        />
      </div>
    </>
  );
}

// Template selected but not started — show DAG preview
if (isIdle && selectedTemplate) {
  const agentDescriptions = useMemo(() => {
    if (!selectedTemplate) return {};
    const wf = selectedTemplate as unknown as { agents: { name: string; description?: string }[] };
    const descMap: Record<string, string> = {};
    for (const a of wf.agents) {
      if (a.description) descMap[a.name] = a.description;
    }
    return descMap;
  }, [selectedTemplate]);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <DAGPreview
          dag={dag}
          agentDescriptions={agentDescriptions}
          onEditAgent={(name) => setEditAgentName(name)}
        />
      </div>
      <div className="shrink-0 border-t border-app-border px-4 py-2 text-center">
        <p className="text-xs text-muted-foreground">
          Ready to start <span className="font-medium">{(selectedTemplate as Record<string, unknown>)?.name as string}</span>
        </p>
      </div>
      <div className="shrink-0">
        <ChatInput startWorkflow={startWorkflow} alwaysVisible />
      </div>
      <AgentEditorModal
        open={editAgentName !== null}
        onOpenChange={(o) => !o && setEditAgentName(null)}
        agentName={editAgentName ?? ""}
        workflowName={effectiveWorkflowName}
      />
    </div>
  );
}
```

**Step 6: Remove benchmark-specific rendering from ScopedCenterPanel**

The current `ScopedCenterPanel` has benchmark view logic (runner/compare/editor tabs). This should stay but verify it reads from scoped stores only — no global store reads for conversation data.

**Step 7: Build and verify**

Run: `cd frontend && npm run build`

**Step 8: Commit**

```
feat: ScopedCenterPanel handles landing page and DAG preview
```

---

### Task 3: Add Refresh Recovery — Pre-populate Stores Before WS Connect

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx`
- Modify: `frontend/src/contexts/workflow-context/useWorkflowWS.ts`

**Why:** On page refresh, scoped stores are rebuilt empty. WebSocket reconnects with `sinceSeq=0`, which replays events from server buffer. But if the buffer overflowed (long-running workflows), early events are lost. We need to REST-fetch current state first, populate stores, then let WS resume from the end.

**Step 1: Add REST pre-population to WorkflowScope**

In `WorkflowScope.tsx`, after the `getOrCreate(workflowId)` call, add a useEffect that fetches run data on mount:

```typescript
useEffect(() => {
  if (!workflowId) return;

  const stores = manager.getStores(workflowId);
  if (!stores) return;

  // Skip if stores already populated (e.g., by showReplay or batch setup)
  if (stores.workflow.getState().dag) return;

  // REST fetch to pre-populate before WS connects
  fetchWithAuth(`/api/runs/${workflowId}`)
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (!data) return;
      // Double-check stores still empty (WS may have connected first)
      if (stores.workflow.getState().dag) return;

      loadRunFromPersistedData(workflowId, {
        agent_io: data.agent_io,
        conversation: data.conversation ?? [],
        dag: data.dag,
        result: data.result,
        chart_groups: data.chart_groups,
        agents_snapshot: data.agents_snapshot,
        workflow_name: data.workflow_name,
        followup_sessions: data.followup_sessions,
      });
    })
    .catch(() => {});
}, [workflowId, manager]);
```

Import `loadRunFromPersistedData` from `./replayEvents` and `fetchWithAuth` from `@/lib/api`.

**Step 2: Change useWorkflowWS sinceSeq strategy**

In `useWorkflowWS.ts`, change from `sinceSeq = 0` (replay all) to using a sequence cursor:

Instead of replaying all events from the beginning, after REST pre-population the stores have current state. The WebSocket should connect with the latest sequence number to avoid replaying already-loaded events.

However, since the current WS protocol uses `sinceSeq=0` to get a full replay from the server's event buffer, and the REST data is more authoritative, we should:

1. Keep `sinceSeq=0` for now (server replays buffer)
2. In `routeEvent.ts`, the `workflow.started` handler already has idempotent reset logic (line 117-131) — it checks `if already processed this workflow_id, skip reset`
3. The REST data will be loaded first, then WS events will arrive but be idempotently handled

This is correct and safe — the idempotency in `routeEvent.ts` prevents double-counting.

**Step 3: Test refresh recovery**

1. Start a workflow with ask_user
2. While question is pending, refresh the page
3. Verify: question card still visible, can still answer
4. Verify: conversation history intact

**Step 4: Commit**

```
feat: REST pre-populate scoped stores before WS reconnect on refresh
```

---

### Task 4: Migrate All Legacy setActiveWorkflowId Callers

**Files:**
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx`
- Modify: `frontend/src/components/output/WorkflowLauncher.tsx`
- Modify: `frontend/src/hooks/useUrlState.ts`
- Modify: `frontend/src/hooks/useResetWorkflow.ts`
- Modify: `frontend/src/stores/userStore.ts`

**Why:** These 5 files import `setActiveWorkflowId` from the legacy `@/hooks/useWorkflowEvents`. They need to use the scoped version from `@/contexts/workflow-context`.

**Step 1: Check if a scoped setActiveWorkflowId already exists**

Read `frontend/src/contexts/workflow-context/index.ts` and check exports. The `setActiveWorkflowId` may already be exported from there (it's listed at line 59 in the export map). If it is, skip to Step 3.

If not, add it. In `frontend/src/contexts/workflow-context/WorkflowManager.ts`, verify the `setActiveWorkflowId` method exists (it should at line 102). Then in `index.ts`, add:

```typescript
export { getWorkflowManager } from "./WorkflowManager";

// Convenience wrapper for setActiveWorkflowId
export function setActiveWorkflowId(id: string | null): void {
  getWorkflowManager().setActiveWorkflowId(id);
}
```

**Step 2: Migrate RunHistoryList.tsx**

Replace the import:
```typescript
// OLD:
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

// NEW:
import { setActiveWorkflowId } from "@/contexts/workflow-context";
```

Verify all usages:
- Line ~151: `setActiveWorkflowId(data.workflow_id ?? runId)` in resume handler — keep as-is
- Line ~163: `setActiveWorkflowId(data.workflow_id)` in rerun handler — keep as-is

The semantic is the same — it tells WorkflowManager which workflow is active.

**Step 3: Migrate WorkflowLauncher.tsx**

Replace the import:
```typescript
// OLD:
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

// NEW:
import { setActiveWorkflowId } from "@/contexts/workflow-context";
```

Usage at line ~111: `setActiveWorkflowId(data.workflow_id)` — keep as-is.

**Step 4: Migrate useUrlState.ts**

Replace the import:
```typescript
// OLD:
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

// NEW:
import { setActiveWorkflowId } from "@/contexts/workflow-context";
```

Usage at line ~63: `setActiveWorkflowId(wid)` — keep as-is.

**Step 5: Migrate useResetWorkflow.ts**

Replace the import:
```typescript
// OLD:
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

// NEW:
import { setActiveWorkflowId } from "@/contexts/workflow-context";
```

Usage at line ~18: `setActiveWorkflowId(null)` — keep as-is.

**Step 6: Migrate userStore.ts**

Replace the import:
```typescript
// OLD:
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

// NEW:
import { setActiveWorkflowId } from "@/contexts/workflow-context";
```

Usage at line ~29: `setActiveWorkflowId(null)` — keep as-is.

**Step 7: Verify no remaining imports of legacy setActiveWorkflowId**

Run: `cd frontend && grep -r "from.*@/hooks/useWorkflowEvents" src/`

Expected: **Zero results**. If any remain, migrate them.

**Step 8: Commit**

```
refactor: migrate all setActiveWorkflowId callers to scoped architecture
```

---

### Task 5: Clean Up WorkflowManager — Remove Dead Code

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowManager.ts`

**Why:** `dispatchEvent()` method (line 165-182) has a TODO and is dead code. All event dispatching goes through `eventRouter.ts` directly. Also need to add a public `setActiveWorkflowId` convenience function.

**Step 1: Remove dispatchEvent dead code**

Delete lines 165-182 from `WorkflowManager.ts`.

**Step 2: Verify nothing calls WorkflowManager.dispatchEvent()**

Run: `cd frontend && grep -r "dispatchEvent" src/contexts/workflow-context/`

Expected: only in `eventRouter.ts` calling its own local functions, not on the manager.

**Step 3: Commit**

```
cleanup: remove dead dispatchEvent from WorkflowManager
```

---

### Task 6: Persist Batch State to URL

**Files:**
- Modify: `frontend/src/stores/batchStore.ts`
- Modify: `frontend/src/hooks/useUrlState.ts`

**Why:** On refresh, `batchStore.activeBatchId` and `selectedRunId` are lost. URL already syncs `?bench=<name>` but doesn't track the selected run within the batch.

**Step 1: Add `task` URL parameter for batch run selection**

In `useUrlState.ts`, extend the URL parameter handling:

```typescript
const PARAM_KEYS = ["run", "wid", "wf", "tab", "bench", "task"] as const;
```

In the restore section (after bench restore), add:

```typescript
const task = params.get("task");
if (bench && task) {
  useBatchStore.getState().setActiveBatch(bench);
  useBatchStore.getState().selectRun(task);
}
```

In the live sync section, add batch state sync:

```typescript
// Sync batch selection to URL
const unsubBatch = useBatchStore.subscribe((state) => {
  const params = readParams();
  if (state.activeBatchId) {
    params.set("bench", state.activeBatchId);
    if (state.selectedRunId) {
      params.set("task", state.selectedRunId);
    } else {
      params.delete("task");
    }
  } else {
    params.delete("bench");
    params.delete("task");
  }
  writeParams(params);
});
```

Add to the cleanup: `unsubBatch()` in the return cleanup.

**Step 2: Test batch persistence**

1. Start a benchmark run
2. Select a task within the batch
3. Refresh the page
4. Verify: benchmark view restored with correct task selected

**Step 3: Commit**

```
feat: persist batch state to URL for refresh recovery
```

---

### Task 7: Delete Legacy Files

**Files:**
- Delete: `frontend/src/hooks/useWorkflowEvents.ts`
- Delete: `frontend/src/components/layout/CenterPanel.tsx`
- Modify: `frontend/src/contexts/workflow-context/useWorkflowWS.ts`

**Why:** After all callers are migrated and `ScopedCenterPanel` handles all modes, these files are dead code.

**Step 1: Verify no remaining imports**

Run: `cd frontend && grep -rn "useWorkflowEvents\|from.*CenterPanel" src/ --include="*.ts" --include="*.tsx" | grep -v "ScopedCenterPanel\|WorkflowCenterPanel"`

Expected: **Zero results**.

If any remain, trace and fix before deleting.

**Step 2: Delete useWorkflowEvents.ts**

```bash
rm frontend/src/hooks/useWorkflowEvents.ts
```

**Step 3: Delete CenterPanel.tsx**

```bash
rm frontend/src/components/layout/CenterPanel.tsx
```

**Step 4: Clean up useWorkflowWS.ts**

In `useWorkflowWS.ts`, remove any references to batch mode detection that relied on the legacy path. The hook should only:
- Connect WS when `workflowId` is not null
- Dispatch events through `dispatchSingleEvent` or `dispatchBatchEvent`
- Return send methods

**Step 5: Build and verify**

Run: `cd frontend && npm run build`

Fix any compilation errors from deleted imports.

**Step 6: Commit**

```
chore: delete legacy useWorkflowEvents and CenterPanel
```

---

### Task 8: End-to-End Verification

**Precondition:** Backend running (`python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`).

**Step 1: Verify landing page**

1. Open http://localhost:3000
2. Verify: Domain Portal renders correctly
3. Click a tutorial card → tutorial page renders
4. Click "Workflows" → workflow list renders
5. Click a workflow card → DAG preview shows
6. Enter a task → workflow starts → conversation streams
7. No errors in browser console (F12)

**Step 2: Verify single workflow live mode**

1. Start a workflow
2. Verify: conversation messages stream in real-time
3. Verify: DAG panel shows node status updates
4. Verify: Results tab shows charts when agents produce them
5. Verify: Diagnostics panel shows trace/tools/errors
6. Wait for completion → status changes to "completed"

**Step 3: Verify replay mode**

1. Click a completed run in sidebar history
2. Verify: "REPLAY" badge shows
3. Verify: conversation shows all messages (not just one agent)
4. Verify: Results tab shows charts
5. Verify: Analysis tab shows summary charts
6. Verify: Diagnostics shows all nodes

**Step 4: Verify ask_user with refresh**

1. Start a workflow that uses ask_user
2. Wait for question card to appear
3. Refresh the page (F5)
4. Verify: question card still visible
5. Select an answer
6. Verify: workflow continues

**Step 5: Verify benchmark mode**

1. Create a benchmark with 2+ tasks
2. Run the benchmark
3. Click on individual tasks → verify each shows its own conversation
4. Switch between tasks → verify no data cross-contamination
5. Wait for completion
6. Refresh the page
7. Verify: benchmark state restored from URL

**Step 6: Verify parallel workflows**

1. Start workflow A
2. While A is running, start workflow B (different task)
3. Switch to A in history → verify only A's conversation
4. Switch to B → verify only B's conversation
5. No message mixing or stacking

**Step 7: Build frontend and deploy**

Run: `cd frontend && npm run build`

Commit build artifacts:
```bash
git add frontend/out/
git commit -m "build: deploy unified architecture frontend"
```

---

## Risk Assessment

| Change | Risk | Severity | Mitigation |
|--------|------|----------|------------|
| Task 1: WorkflowCenterPanel rewrite | Breaks landing → workflow transition | High | Task 2 must be done first or together |
| Task 2: ScopedCenterPanel landing page | Missing functionality from CenterPanel | High | Step-by-step migration with verification |
| Task 3: REST pre-population | Race condition: REST data + WS events arrive simultaneously | Medium | Idempotent handlers in routeEvent.ts (already implemented) |
| Task 4: Migrate callers | Missing import causes crash | Low | TypeScript compiler catches missing imports |
| Task 6: Batch URL persistence | URL param conflicts with existing params | Low | Separate `task` param, tested in isolation |
| Task 7: Delete legacy files | Hidden runtime dependency not caught by compiler | Medium | Grep verification in Step 1 + full E2E test |

## Execution Order Dependency

```
Task 2 (ScopedCenterPanel landing) → Task 1 (WorkflowCenterPanel rewrite) → Task 4 (migrate callers)
Task 3 (refresh recovery) — independent, can run in parallel
Task 5 (cleanup) — after Task 4
Task 6 (batch persistence) — independent, can run in parallel
Task 7 (delete legacy) — after Tasks 1, 2, 4
Task 8 (verification) — after all others
```

Recommended batch execution:
- **Batch 1**: Tasks 2 + 3 + 6 (parallel, independent changes)
- **Batch 2**: Tasks 1 + 4 (sequential, depends on Batch 1)
- **Batch 3**: Tasks 5 + 7 (cleanup)
- **Batch 4**: Task 8 (verification)

## Critical Files Reference

| File | Role | Lines |
|------|------|-------|
| `frontend/src/hooks/useWorkflowEvents.ts` | LEGACY — to be deleted | ~530 lines |
| `frontend/src/components/layout/CenterPanel.tsx` | LEGACY — to be deleted | ~466 lines |
| `frontend/src/components/layout/WorkflowCenterPanel.tsx` | Entry point, WS lifecycle | ~74 lines |
| `frontend/src/components/layout/ScopedCenterPanel.tsx` | Tab rendering, chat | ~350 lines |
| `frontend/src/contexts/workflow-context/routeEvent.ts` | Single event routing switch | ~442 lines |
| `frontend/src/contexts/workflow-context/WorkflowManager.ts` | Workflow lifecycle | ~314 lines |
| `frontend/src/contexts/workflow-context/replayEvents.ts` | Data restoration | ~450 lines |
| `frontend/src/stores/viewStore.ts` | View mode management | ~81 lines |
| `frontend/src/stores/batchStore.ts` | Batch state | ~100 lines |
| `frontend/src/hooks/useUrlState.ts` | URL sync | ~128 lines |
