# Historical Run Fidelity Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clicking a historical workflow run shows identical UI to a live run just completed — conversation, agent tools/IO, analysis charts, diagnostics, results all present.

**Architecture:** The root cause is that `replayEventsToStores()` skips `workflow.started` and `workflow.completed` lifecycle events. This means DAG is never set (no graph rendered), status stays "idle", and `computeRunSummary()` is never called (no analysis charts). Fix by extracting the non-API side effects from lifecycle events into reusable helpers, calling them during replay, and ensuring backend always persists all fields.

**Tech Stack:** TypeScript (React/Zustand), Python (FastAPI/Pydantic)

---

## Root Cause Summary

| Symptom | Root Cause | File:Line |
|---------|-----------|-----------|
| No analysis charts in history | `replayEventsToStores` skips `workflow.completed` → `computeRunSummary()` never called | `replayEvents.ts:257-262` |
| No DAG graph in history | `workflow.started` skipped → `handleWorkflowStarted()` never called → `dag` stays null | `replayEvents.ts:257-262` |
| Status shows "idle" in history | `workflow.completed` skipped → `handleWorkflowCompleted()` never called | `replayEvents.ts:257-262` |
| Old runs missing `events`/`chart_groups`/`conversation` fields | `RunStore.save()` uses `if field:` guard — empty lists are falsy | `run_store.py:57-70` |
| REST fallback overwrites live WS data | Only checks DAG presence, not completion status | `WorkflowScope.tsx:94` |
| ScopedConversationTab gets no agentIO | `workflow.started` skipped → DAG null → nodes empty → `getAgentIO`/`getNodeState` return undefined | `ScopedConversationTab.tsx:96-100` |

---

### Task 1: Fix `replayEventsToStores` — Handle lifecycle events for UI state

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts:257-301`

**Why:** This is the P0 root cause. All downstream UI gaps trace back to replay skipping lifecycle events. We must process `workflow.started` (to set DAG/name/status) and `workflow.completed` (to set status + compute summary charts) during replay, while still skipping the API-call side effects (`saveConversation`, `saveCharts`).

**Step 1: Add lifecycle event handling in `routeReplayEvent`**

Replace the `default: break` at lines 257-263 with explicit lifecycle handlers:

```typescript
// -- Lifecycle events: populate UI state only (no API calls) -------

case "workflow.started": {
  const p = payload<WorkflowStartedPayload>(event);
  stores.workflow.getState().setActiveWorkflowId(p.workflow_id);
  stores.workflow.getState().handleWorkflowStarted(p);
  stores.span.getState().setWorkflowStartTs(event.ts);
  break;
}

case "workflow.completed": {
  const p = payload<WorkflowCompletedPayload>(event);
  stores.workflow.getState().handleWorkflowCompleted(p);
  // Compute summary charts from replayed node data
  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  const addChart = stores.chart.getState().addChart;
  computeRunSummary(summaryNodes, addChart, stores.span);
  break;
}

case "workflow.error": {
  const p = payload<{ workflow_id: string; error: string }>(event);
  stores.workflow.getState().handleWorkflowCompleted({
    workflow_id: p.workflow_id,
    status: "failed",
  });
  stores.output.getState().setWorkflowError(p.error);
  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  const addChart = stores.chart.getState().addChart;
  computeRunSummary(summaryNodes, addChart, stores.span);
  break;
}

case "workflow.cancelled": {
  const p = payload<{ workflow_id: string }>(event);
  stores.workflow.getState().handleWorkflowCompleted({
    workflow_id: p.workflow_id,
    status: "paused",
  });
  break;
}

case "workflow.resumed": {
  const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
  stores.conversation.getState().resumeAgentMessage(p.node_id, "");
  break;
}

// -- Span events (already handled, but lifecycle deps need these) ---
case "span.start": {
  const p = payload<SpanStartPayload>(event);
  stores.span.getState().startSpan(p);
  break;
}
case "span.end": {
  const p = payload<SpanEndPayload>(event);
  stores.span.getState().endSpan(p.span_id, p.ts);
  break;
}

// -- Unrecognized events: skip ------------------------------------
default:
  break;
```

**Step 2: Add required imports at top of file**

Add to existing imports in `replayEvents.ts`:

```typescript
import type {
  // ... existing imports ...
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  SpanStartPayload,
  SpanEndPayload,
} from "@/types/events";
import { computeRunSummary } from "@/lib/summary/runSummary";
```

**Step 3: Remove the post-replay `setActiveWorkflowId` call**

In `replayEventsToStores()` (lines 288-300), remove line 289 since `workflow.started` event now handles it:

```typescript
// Before:
// 2. Set the active workflow ID so the workflow store is initialized
stores.workflow.getState().setActiveWorkflowId(workflowId);

// After: (remove this line — workflow.started event will set it)
```

**Step 4: Run the frontend dev server and test**

Run: `cd frontend && npm run dev`

Test: Start a workflow run, wait for completion, then click the run in history sidebar. Verify:
- DAG graph renders in left panel
- Conversation tab shows all agent messages with tools
- Results tab shows custom charts
- Analysis tab shows summary charts (Tokens, Duration, Cost, Timeline, Overview)
- Diagnostics panel shows trace/tools/errors with correct counts

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts
git commit -m "fix: replay lifecycle events for full history fidelity"
```

---

### Task 2: Fix `loadLegacyRunData` — Compute summary for old runs without events

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts:311-363`

**Why:** Old runs (before events were persisted) use `loadLegacyRunData`. This path never sets DAG, workflow status, or computes summary charts. Users clicking old history see empty panels.

**Step 1: Add DAG/status/summary to `loadLegacyRunData`**

Change the function signature and add missing state:

```typescript
export function loadLegacyRunData(
  workflowId: string,
  conversation: any[],
  chartGroups: { groups: Record<string, any>; groupOrder: string[] } | null,
  dag?: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null,
  workflowName?: string,
  runResult?: { trace: Array<{ agent_name: string; status: string; duration_ms: number; error: string | null; token_usage?: { input: number; output: number; total: number } | null }> } | null,
): void {
  const manager = getWorkflowManager();
  const stores = manager.getOrCreate(workflowId).stores;

  stores.conversation.getState().reset();
  stores.chart.getState().reset();
  stores.workflow.getState().reset();

  // Set DAG and workflow status if available
  if (dag) {
    stores.workflow.getState().handleWorkflowStarted({
      workflow_id: workflowId,
      name: workflowName ?? "",
      dag,
      inputs: {},
    });
  }

  // Build node states from result.trace
  if (runResult?.trace) {
    for (const t of runResult.trace) {
      stores.workflow.getState().handleNodeStarted({
        node_id: t.agent_name,
        agent_name: t.agent_name,
        attempt: 0,
      });
      if (t.status === "success") {
        stores.workflow.getState().handleNodeCompleted({
          node_id: t.agent_name,
          agent_name: t.agent_name,
          duration_ms: t.duration_ms,
          token_usage: t.token_usage ?? undefined,
        });
      } else {
        stores.workflow.getState().handleNodeFailed({
          node_id: t.agent_name,
          agent_name: t.agent_name,
          error: t.error ?? "Unknown error",
          duration_ms: t.duration_ms,
          attempt: 0,
          will_retry: false,
        });
      }
    }
  }

  // Mark workflow as completed
  stores.workflow.getState().handleWorkflowCompleted({
    workflow_id: workflowId,
    status: "completed",
  });

  // ... existing conversation/chart loading code stays the same ...

  // Compute summary charts from reconstructed node data
  const summaryNodes = Object.values(stores.workflow.getState().nodes);
  if (summaryNodes.length > 0) {
    const addChart = stores.chart.getState().addChart;
    computeRunSummary(summaryNodes, addChart, stores.span);
  }

  manager.setWorkflowStatus(workflowId, "completed");
}
```

**Step 2: Add import for `computeRunSummary`**

(Same import as Task 1 — already added)

**Step 3: Update callers of `loadLegacyRunData`**

In `viewStore.ts:39`:

```typescript
// Before:
loadLegacyRunData(run.run_id, run.conversation ?? [], run.chart_groups ?? null);

// After:
loadLegacyRunData(
  run.run_id,
  run.conversation ?? [],
  run.chart_groups ?? null,
  run.dag,
  run.workflow_name,
  run.result,
);
```

In `WorkflowScope.tsx:121`:

```typescript
// Before:
loadLegacyRunData(workflowId, data.conversation ?? [], data.chart_groups ?? null);

// After:
loadLegacyRunData(
  workflowId,
  data.conversation ?? [],
  data.chart_groups ?? null,
  data.dag,
  data.workflow_name,
  data.result,
);
```

**Step 4: Test with an old run (no events field)**

If no old runs exist, create one by manually deleting the `events` field from a run JSON file in `runs/`. Click it in history and verify DAG, conversation, results, analysis all render.

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts frontend/src/stores/viewStore.ts frontend/src/contexts/workflow-context/WorkflowScope.tsx
git commit -m "fix: legacy run data now sets DAG, status, and summary charts"
```

---

### Task 3: Fix REST fallback guard — Don't overwrite completed runs

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx:85-147`

**Why:** The REST fallback checks only `stores.workflow.getState().dag` — if DAG arrives via WS but other data hasn't yet, the fallback still fires after 5s and resets all stores. This causes results to disappear right after a run completes.

**Step 1: Strengthen the guard condition**

Replace line 94:

```typescript
// Before:
if (stores.workflow.getState().dag) return;

// After:
const wfState = stores.workflow.getState();
// Don't overwrite if we already have a DAG and the workflow is in a terminal state
if (wfState.dag && (wfState.status === "completed" || wfState.status === "failed" || wfState.status === "paused")) return;
// Also don't overwrite if we have a DAG and nodes are being populated (WS events arriving)
if (wfState.dag && Object.keys(wfState.nodes).length > 0) return;
```

**Step 2: Commit**

```bash
git add frontend/src/contexts/workflow-context/WorkflowScope.tsx
git commit -m "fix: REST fallback no longer overwrites live WS data for completed runs"
```

---

### Task 4: Fix `RunStore.save()` — Always persist all fields

**Files:**
- Modify: `harness/run_store.py:47-75`

**Why:** `if conversation:` skips `[]`. `if chart_groups:` skips `{}`. `if events:` skips `[]`. This means the JSON file may lack these fields entirely, causing the frontend to get `undefined` instead of empty arrays/objects.

**Step 1: Change conditional writes to always-write with defaults**

```python
# Before (lines 57-70):
if agent_io:
    record["agent_io"] = agent_io
if batch_id:
    record["batch_id"] = batch_id
if user_id:
    record["user_id"] = user_id
if chart_groups:
    record["chart_groups"] = chart_groups
if conversation:
    record["conversation"] = conversation
if events:
    record["events"] = events
if work_dir:
    record["work_dir"] = work_dir

# After:
# Always write optional fields — frontend expects them present even if empty/null
record["agent_io"] = agent_io or None
record["batch_id"] = batch_id or None
record["user_id"] = user_id or None
record["chart_groups"] = chart_groups or None
record["conversation"] = conversation if conversation is not None else []
record["events"] = events if events is not None else None
record["work_dir"] = work_dir or None
```

**Step 2: Run existing tests**

Run: `pytest tests/harness/ -v`

Verify no regressions. The change is backward-compatible — existing JSON files with missing fields still parse fine, and the `/api/runs/{id}` endpoint already applies Pydantic defaults.

**Step 3: Commit**

```bash
git add harness/run_store.py
git commit -m "fix: always persist all run fields to JSON for frontend consistency"
```

---

### Task 5: Fix `showReplay` in viewStore — Ensure DAG and result propagate

**Files:**
- Modify: `frontend/src/stores/viewStore.ts:21-43`

**Why:** `showReplay()` calls `replayEventsToStores()` or `loadLegacyRunData()`, but if the `workflow.started` event isn't in the events array (e.g. it was dropped), the DAG won't be set. We should always explicitly set DAG and status after replay as a safety net.

**Step 1: Add post-replay DAG/status safety net in `showReplay`**

```typescript
showReplay: (run) => {
  // Populate agentIOStore from persisted run data (backward compat)
  if (run.agent_io) {
    const store = useAgentIOStore.getState();
    for (const [nodeId, io] of Object.entries(run.agent_io)) {
      store.setAgentIO(nodeId, io.input_prompt ?? "", io.output_result, io.system_prompt);
    }
  }

  // Ensure scoped stores exist for this workflow
  const manager = getWorkflowManager();
  manager.getOrCreate(run.run_id);

  // New path: replay events into scoped stores
  // Backward compat: load legacy data directly
  if (run.events && run.events.length > 0) {
    replayEventsToStores(run.run_id, run.events as WSEvent[]);
  } else {
    loadLegacyRunData(
      run.run_id,
      run.conversation ?? [],
      run.chart_groups ?? null,
      run.dag,
      run.workflow_name,
      run.result,
    );
  }

  // Safety net: ensure DAG and status are set even if events lacked workflow.started
  const stores = manager.getStores(run.run_id);
  if (stores) {
    const wfState = stores.workflow.getState();
    if (!wfState.dag && run.dag) {
      wfState.handleWorkflowStarted({
        workflow_id: run.run_id,
        name: run.workflow_name,
        dag: run.dag,
        inputs: run.inputs,
      });
    }
    if (wfState.status === "idle") {
      wfState.handleWorkflowCompleted({
        workflow_id: run.run_id,
        status: run.status === "failed" ? "failed" : "completed",
      });
    }
    // Compute summary if charts are empty but we have nodes
    const chartState = stores.chart.getState();
    const hasAnalysis = chartState.groupOrder.some(
      (label) => chartState.groups[label]?.category === "analysis"
    );
    if (!hasAnalysis && Object.keys(wfState.nodes).length > 0) {
      const summaryNodes = Object.values(wfState.nodes);
      const addChart = chartState.addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
    }
  }

  set({ activeView: { type: "replay", runId: run.run_id, run } });
},
```

**Step 2: Add required imports to viewStore.ts**

```typescript
import { computeRunSummary } from "@/lib/summary/runSummary";
```

**Step 3: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "fix: safety net for DAG/status/summary in showReplay"
```

---

### Task 6: Fix DiagnosticsPanel — Remove redundant `useReplayDerived` fallback

**Files:**
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx:98-134`

**Why:** The `ScopedDiagnosticsPanel` has a `useReplayDerived` hook that re-derives nodes from `activeView.run.result.trace` instead of using the scoped stores. Since Task 1 now populates scoped stores correctly during replay, this fallback is unnecessary and can cause inconsistencies (e.g., node IDs from trace use `agent_name` while store uses `node_id`).

**Step 1: Simplify `ScopedDiagnosticsPanel` to always use scoped stores**

```typescript
function ScopedDiagnosticsPanel({ stores }: { stores: WorkflowStores }) {
  const nodes = useStore(stores.workflow, (s) => s.nodes);
  const status = useStore(stores.workflow, (s) => s.status);
  const selectedNodeId = useStore(stores.workflow, (s) => s.selectedNodeId);
  const toolRecords = useStore(stores.toolCall, (s) => s.records);
  const toolOrder = useStore(stores.toolCall, (s) => s.order);
  const circularWarnings = useObservabilityStore((s) => s.circularWarnings);

  const [activeTab, setActiveTab] = useState("trace");

  useEffect(() => {
    if (selectedNodeId) setActiveTab("trace");
  }, [selectedNodeId]);

  useEffect(() => {
    if (status === "idle") {
      useObservabilityStore.getState().clear();
    }
  }, [status]);

  const toolCallCount = toolOrder.length;
  const errorCount = countErrors(nodes);

  return renderPanel({
    activeTab, setActiveTab, nodes, status,
    toolRecords, toolOrder, toolCallCount, errorCount,
    replayDerived: null,
    circularWarnings,
    scopedStores: stores,
  });
}
```

**Step 2: Keep `useReplayDerived` only in `GlobalDiagnosticsPanel`**

The global fallback panel still needs `useReplayDerived` since it doesn't have scoped stores. No change needed there.

**Step 3: Test**

Click a historical run → Diagnostics panel should show:
- Trace tab: all nodes with correct status, duration, token counts
- Tools tab: all tool calls with args and results
- Errors tab: any failed nodes

**Step 4: Commit**

```bash
git add frontend/src/components/diagnostics/DiagnosticsPanel.tsx
git commit -m "fix: scoped diagnostics uses store data instead of replay-derived fallback"
```

---

### Task 7: Frontend build and integration test

**Files:**
- No new files — just verification

**Step 1: Build frontend**

Run: `cd frontend && npm run build`

Fix any TypeScript compilation errors.

**Step 2: Start the full stack and manually test**

Run: `bash examples/launch_ui.sh`

Test matrix:
1. Start a workflow → watch it complete live → all tabs populated
2. Click the same run in history → all tabs should show identical data
3. Click an old run (no events field) → should still show conversation, charts, DAG
4. Click a running workflow in history → should switch to live view with WS
5. Start a run → immediately click away → come back → data should be intact (no REST fallback overwrite)

**Step 3: Commit build artifacts**

```bash
git add frontend/out/
git commit -m "build: frontend rebuild after history fidelity fix"
```

---

### Task 8: Push and verify

**Step 1: Push to main**

```bash
git push origin main
```

**Step 2: Verify deployment**

Open the deployed UI and repeat the test matrix from Task 7.

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Replay handling lifecycle events | Double-setting DAG/status if events include both workflow.started AND the safety net | Safety net checks `!wfState.dag` before setting |
| `loadLegacyRunData` signature change | Callers not updated | Both callers updated in Task 2 Step 3 |
| RunStore always-write | Larger JSON files | Negligible — `None` is just 4 bytes |
| Removing `useReplayDerived` from scoped panel | May lose node data if scoped stores aren't populated | Task 1 ensures stores are populated; safety net in Task 5 adds double protection |
