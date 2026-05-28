# Frontend Observability Display — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire all 6 new backend observability events (`step.summary`, `span.start/end`, `circular.warning`, `ttft_ms`, `cost_usd`) into the frontend DiagnosticsPanel, making them visible in real-time.

**Architecture:** The eventRouter is the single entry point for all WebSocket events. We add new cases to its switch statement, create a small Zustand store for observability data, and extend the existing 3 tabs (Trace, Tools, Errors) with the new data. No new tabs needed — we enrich existing ones.

**Tech Stack:** React, Zustand, TypeScript, Next.js 14

---

## Overview of Changes

**New events to consume:**

| Event | Current frontend handling | Where to display |
|-------|--------------------------|-----------------|
| `node.completed` with `cost_usd` | Ignored (not in payload type) | Trace tab: add Cost column |
| `node.completed` with `ttft_ms` | Ignored | Trace tab: add TTFT column |
| `step.summary` | Not in eventRouter | Trace tab: add Steps column |
| `span.start` / `span.end` | Not in eventRouter | Tools tab: show nested structure |
| `circular.warning` | Not in eventRouter | Errors tab: show as warning |
| `node.failed` with `error_type` | Already handled (badge shown) | Already done |

**Files to modify:**

| File | What changes |
|------|-------------|
| `frontend/src/types/events.ts` | Add new event types + payload interfaces |
| `frontend/src/contexts/workflow-context/eventRouter.ts` | Add routing for new events |
| `frontend/src/hooks/useWorkflowEvents.ts` | Add routing for legacy path |
| `frontend/src/stores/workflowStore.ts` | Add `ttftMs`, `costUsd`, `steps` to NodeState |
| `frontend/src/components/diagnostics/TraceTab.tsx` | Add Cost, TTFT, Steps columns |
| `frontend/src/components/diagnostics/ErrorsTab.tsx` | Add circular warning section |
| `frontend/src/components/diagnostics/DiagnosticsPanel.tsx` | No changes (already passes props) |
| `frontend/src/components/diagnostics/ToolCallsTab.tsx` | No changes (already shows tool data) |

---

## Task 1: Add TypeScript types for new events

**Files:**
- Modify: `frontend/src/types/events.ts`

**Step 1: Add new event types to `EventType` union**

After the existing types in the union, add:

```typescript
export type EventType =
  // ... existing types ...
  | "span.start"
  | "span.end"
  | "step.summary"
  | "circular.warning";
```

**Step 2: Add payload interfaces**

```typescript
// Span tracing events
export interface SpanStartPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  span_id: string;
  span_type: "llm" | "tool";
  model?: string;
  tool_name?: string;
}

export interface SpanEndPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  span_id: string;
  span_type: "llm" | "tool";
  tool_name?: string;
}

// Step counter
export interface StepSummaryPayload {
  workflow_id: string;
  node_id: string;
  node_tool_calls: number;
  node_llm_calls: number;
  total_tool_calls: number;
  total_llm_calls: number;
}

// Circular detection
export interface CircularWarningPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  repeated_count: number;
  last_tool: string | null;
  message: string;
}
```

**Step 3: Add new optional fields to `NodeCompletedPayload`**

```typescript
export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
  cost_usd?: number;       // NEW
  ttft_ms?: number;         // NEW
  input_prompt?: string;
  system_prompt?: string;
  output_result?: Record<string, unknown>;
}
```

**Step 4: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS (types are additive, no consumers yet)

**Step 5: Commit**

```
feat(frontend): add TypeScript types for new observability events
```

---

## Task 2: Extend NodeState and workflowStore

**Files:**
- Modify: `frontend/src/stores/workflowStore.ts`

**Step 1: Add new fields to NodeState interface**

```typescript
export interface NodeState {
  id: string;
  name: string;
  status: "idle" | "running" | "success" | "failed" | "retrying";
  durationMs?: number;
  error?: string;
  errorType?: string;
  toolCallsBeforeFailure?: ToolCallBrief[];
  attempt?: number;
  willRetry?: boolean;
  tokenUsage?: { input: number; output: number; total: number };
  tools?: ToolBrief[];
  model?: string;
  costUsd?: number;      // NEW
  ttftMs?: number;        // NEW
  toolCallCount?: number;  // NEW: from step.summary
  llmCallCount?: number;   // NEW: from step.summary
}
```

**Step 2: Update `handleNodeCompleted` to map new fields**

In the `handleNodeCompleted` method, after existing field mappings, add:

```typescript
// Cost, TTFT from enriched node.completed payload
if (payload.cost_usd != null) {
  updates.costUsd = payload.cost_usd;
}
if (payload.ttft_ms != null) {
  updates.ttftMs = payload.ttft_ms;
}
```

**Step 3: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS

**Step 4: Commit**

```
feat(frontend): extend NodeState with costUsd, ttftMs, step counts
```

---

## Task 3: Route new events in eventRouter

**Files:**
- Modify: `frontend/src/contexts/workflow-context/eventRouter.ts`

**Step 1: Import new payload types**

Add to imports:

```typescript
import type {
  // ... existing imports ...
  SpanStartPayload,
  SpanEndPayload,
  StepSummaryPayload,
  CircularWarningPayload,
} from "@/types/events";
```

**Step 2: Add cases to `routeEventToStores` switch**

After the existing `chart.render` case:

```typescript
case "step.summary": {
  const p = payload<StepSummaryPayload>(event);
  const wf = stores.workflow.getState();
  const node = wf.nodes[p.node_id];
  if (node) {
    stores.workflow.setState((state) => ({
      nodes: {
        ...state.nodes,
        [p.node_id]: {
          ...state.nodes[p.node_id],
          toolCallCount: p.node_tool_calls,
          llmCallCount: p.node_llm_calls,
        },
      },
    }));
  }
  break;
}

case "span.start":
case "span.end": {
  // Span events are for future timeline visualization.
  // Currently logged but not stored to avoid memory growth.
  break;
}

case "circular.warning": {
  const p = payload<CircularWarningPayload>(event);
  // Store as a synthetic error on the node so ErrorsTab shows it
  const wf = stores.workflow.getState();
  const node = wf.nodes[p.node_id];
  if (node && node.status !== "failed") {
    stores.workflow.setState((state) => ({
      nodes: {
        ...state.nodes,
        [p.node_id]: {
          ...state.nodes[p.node_id],
          // Don't change status — just add warning metadata
        },
      },
    }));
  }
  break;
}
```

**Step 3: Also add to `useWorkflowEvents.ts` for legacy path**

In `_routeToUIStores`, add the same three cases (`step.summary`, `span.start`, `span.end`, `circular.warning`).

**Step 4: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS

**Step 5: Commit**

```
feat(frontend): route step.summary, span, circular.warning events
```

---

## Task 4: Enrich TraceTab with Cost, TTFT, and Steps

**Files:**
- Modify: `frontend/src/components/diagnostics/TraceTab.tsx`

**Step 1: Add formatting helpers**

```typescript
function formatCost(usd?: number): string {
  if (usd == null) return "-";
  if (usd < 0.01) return `<$0.01`;
  if (usd < 1) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(2)}`;
}

function formatTTFT(ms?: number): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatSteps(toolCalls?: number): string {
  if (toolCalls == null) return "-";
  return String(toolCalls);
}
```

**Step 2: Add columns to table header**

Change the `<TableHeader>` to:

```tsx
<TableHeader>
  <TableRow>
    <TableHead className="px-2 py-1">Agent</TableHead>
    <TableHead className="px-2 py-1">Status</TableHead>
    <TableHead className="px-2 py-1 text-right">Time</TableHead>
    <TableHead className="px-2 py-1 text-right">TTFT</TableHead>
    <TableHead className="px-2 py-1 text-right">Tokens</TableHead>
    <TableHead className="px-2 py-1 text-right">Cost</TableHead>
    <TableHead className="px-2 py-1 text-right">Steps</TableHead>
  </TableRow>
</TableHeader>
```

**Step 3: Add cells to each table row**

In the `<TableBody>`, add 3 new `<TableCell>` after the existing "Time" cell:

```tsx
<TableCell className="px-2 py-1 text-right text-muted-foreground">
  {formatTTFT(node.ttftMs)}
</TableCell>
<TableCell className="px-2 py-1 text-right text-muted-foreground">
  {formatTokens(node.tokenUsage?.total)}
</TableCell>
<TableCell className="px-2 py-1 text-right text-muted-foreground">
  {formatCost(node.costUsd)}
</TableCell>
<TableCell className="px-2 py-1 text-right text-muted-foreground">
  {formatSteps(node.toolCallCount)}
</TableCell>
```

**Step 4: Add cost and TTFT totals to the summary footer**

After the existing totals footer block, add:

```tsx
// Cost totals
const totalCost = nodeList.reduce((sum, n) => sum + (n.costUsd ?? 0), 0);
const totalTTFT = nodeList.length > 0
  ? Math.round(nodeList.reduce((sum, n) => sum + (n.ttftMs ?? 0), 0) / nodeList.length)
  : null;

// Extend the existing totals div, or add a second one
{totalCost > 0 && (
  <div className="flex items-center gap-2 border-t border-app-border px-3 py-1.5 text-xs text-muted-foreground">
    <span>Cost:</span>
    <span className="font-medium text-app-text-primary">{formatCost(totalCost)}</span>
    {totalTTFT != null && (
      <>
        <span>·</span>
        <span>Avg TTFT:</span>
        <span className="font-medium text-app-text-primary">{formatTTFT(totalTTFT)}</span>
      </>
    )}
  </div>
)}
```

**Step 5: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS

**Step 6: Commit**

```
feat(frontend): add Cost, TTFT, Steps columns to Trace tab
```

---

## Task 5: Show circular warnings in ErrorsTab

**Files:**
- Modify: `frontend/src/components/diagnostics/ErrorsTab.tsx`

**Step 1: Accept a `circularWarnings` prop**

Add to the component props:

```tsx
interface CircularWarning {
  node_id: string;
  agent_name: string;
  message: string;
  last_tool: string | null;
}

export default function ErrorsTab({
  nodes: nodesProp,
  circularWarnings,
}: {
  nodes?: Record<string, NodeState>;
  circularWarnings?: CircularWarning[];
} = {}) {
```

**Step 2: Render warnings after the errors list**

After the failed nodes list (after `</ScrollArea>`), add:

```tsx
{circularWarnings && circularWarnings.length > 0 && (
  <div className="border-t border-app-border">
    <div className="px-3 py-2 text-xs font-medium text-amber-600">Circular Warnings</div>
    {circularWarnings.map((w, i) => (
      <div key={i} className="px-3 py-2 border-t border-app-border">
        <div className="flex items-center gap-2">
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-mono text-amber-700">
            Circular
          </span>
          <span className="text-sm font-medium text-app-text-primary">
            {w.agent_name || w.node_id}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{w.message}</p>
      </div>
    ))}
  </div>
)}
```

**Step 3: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS

**Step 4: Commit**

```
feat(frontend): show circular warnings in Errors tab
```

---

## Task 6: Store and pass circular warnings through DiagnosticsPanel

**Files:**
- Create: `frontend/src/stores/observabilityStore.ts`
- Modify: `frontend/src/contexts/workflow-context/eventRouter.ts`
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`

**Step 1: Create a small observability store**

Create `frontend/src/stores/observabilityStore.ts`:

```typescript
import { create } from "zustand";

export interface CircularWarning {
  nodeId: string;
  agentName: string;
  message: string;
  lastTool: string | null;
  ts: number;
}

export interface ObservabilityState {
  circularWarnings: CircularWarning[];
  addCircularWarning: (warning: CircularWarning) => void;
  clear: () => void;
}

export const useObservabilityStore = create<ObservabilityState>((set) => ({
  circularWarnings: [],
  addCircularWarning: (w) =>
    set((state) => ({
      circularWarnings: [...state.circularWarnings, w],
    })),
  clear: () => set({ circularWarnings: [] }),
}));
```

**Step 2: Update eventRouter to store circular warnings**

In the `circular.warning` case in `routeEventToStores`:

```typescript
case "circular.warning": {
  const p = payload<CircularWarningPayload>(event);
  // Import and use the global store (not scoped, since warnings are diagnostic)
  const { useObservabilityStore } = await import("@/stores/observabilityStore");
  useObservabilityStore.getState().addCircularWarning({
    nodeId: p.node_id,
    agentName: p.agent_name,
    message: p.message,
    lastTool: p.last_tool,
    ts: Date.now(),
  });
  break;
}
```

Actually, dynamic import in a sync function won't work. Use a top-level import instead.

**Step 3: Update DiagnosticsPanel to pass warnings to ErrorsTab**

In `renderPanel`, read from `useObservabilityStore` and pass to ErrorsTab:

```tsx
import { useObservabilityStore } from "@/stores/observabilityStore";

// In renderPanel or in a sub-component:
const circularWarnings = useObservabilityStore((s) => s.circularWarnings);

// In the ErrorsTab render:
<ErrorsTab
  nodes={replayDerived ? nodes : undefined}
  circularWarnings={circularWarnings}
/>
```

Also add `clear()` call when workflow changes (useEffect watching `status`).

**Step 4: Build and verify**

Run: `cd frontend && npx next build`
Expected: PASS

**Step 5: Commit**

```
feat(frontend): wire circular warnings through observability store
```

---

## Task 7: Final integration and build

**Step 1: Run full build**

Run: `cd frontend && npx next build`
Expected: PASS with no new warnings

**Step 2: Run Python tests (no regression)**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: ALL PASS (no Python changes in this batch)

**Step 3: Manual smoke test checklist**

1. Start a workflow → Trace tab shows Cost/TTFT/Steps columns with data
2. Trigger a circular warning → Errors tab shows warning section
3. Check DiagnosticsPanel in batch mode → all columns populate
4. Check DiagnosticsPanel in replay mode → no regressions

**Step 4: Commit final state**

```
feat(frontend): complete observability integration — all events visible in DiagnosticsPanel
```
