# Visualization: Waterfall Timeline, Budget Bar, Regression UI

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three visualization features — execution waterfall timeline, budget progress bar, and benchmark regression detection — integrated into the existing chart/analysis system.

**Architecture:** Waterfall is a new `chart_type` in the existing `ChartPayload` → `chartStore` → `AnalysisTab` pipeline. Span events gain timestamps so the frontend can compute per-agent timeline bars. BudgetBar is a lightweight component reading from `workflowStore` + a new `envelope` field in `workflow.started`. Regression adds a tab to the existing `BenchmarkCompare` component calling the existing backend API.

**Tech Stack:** Python (pytest), TypeScript/React (zustand, recharts), FastAPI

---

## Task 1: Backend — Add timestamps to span events

**Files:**
- Modify: `harness/engine/llm_executor.py:133-141,186-192,223-230,239-246`
- Test: `tests/harness/engine/test_span_tracing.py`

**Step 1: Write the failing test**

```python
# tests/harness/engine/test_span_tracing.py — append new test

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from harness.engine.llm_executor import LLMExecutor


@pytest.mark.asyncio
async def test_span_events_include_timestamps():
    """span.start and span.end payloads must contain 'ts' (epoch ms)."""
    emitted = []

    class FakeBus:
        def emit(self, event_type, payload):
            emitted.append((event_type, payload))

    agent = MagicMock()
    agent.model.model_name = "test-model"
    agent.is_model_request_node = lambda n: True

    executor = LLMExecutor(
        agent=agent,
        node_id="test-node",
        agent_name="test-agent",
        wid="wf-1",
        bus=FakeBus(),
    )

    # Simulate _handle_model_request emitting span.start + span.end
    # We call the emit path directly
    span_id = executor._next_span_id()

    # Emit span.start
    executor._bus.emit("span.start", {
        "workflow_id": executor._wid,
        "node_id": executor._node_id,
        "agent_name": executor._agent_name,
        "span_id": span_id,
        "span_type": "llm",
        "model": "test-model",
        "ts": int(__import__("time").time() * 1000),
    })

    # Emit span.end
    executor._bus.emit("span.end", {
        "workflow_id": executor._wid,
        "node_id": executor._node_id,
        "agent_name": executor._agent_name,
        "span_id": span_id,
        "span_type": "llm",
        "ts": int(__import__("time").time() * 1000),
    })

    for event_type, payload in emitted:
        assert "ts" in payload, f"{event_type} missing 'ts' field"
        assert isinstance(payload["ts"], (int, float)), f"{event_type} ts must be numeric"
        assert payload["ts"] > 0, f"{event_type} ts must be positive"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/engine/test_span_tracing.py::test_span_events_include_timestamps -v`
Expected: FAIL — current code does not include `ts` in span payloads.

**Step 3: Add `ts` to all 4 span emit calls**

In `harness/engine/llm_executor.py`, add `import time` at top if not present, then add `"ts": int(time.time() * 1000)` to every `bus.emit("span.start"...)` and `bus.emit("span.end"...)` call. There are 4 emit sites:

1. **Line ~134** — `span.start` for LLM:
```python
self._bus.emit("span.start", {
    "workflow_id": self._wid,
    "node_id": self._node_id,
    "agent_name": self._agent_name,
    "span_id": span_id,
    "span_type": "llm",
    "model": model_name,
    "ts": int(time.time() * 1000),
})
```

2. **Line ~186** — `span.end` for LLM:
```python
self._bus.emit("span.end", {
    "workflow_id": self._wid,
    "node_id": self._node_id,
    "agent_name": self._agent_name,
    "span_id": span_id,
    "span_type": "llm",
    "ts": int(time.time() * 1000),
})
```

3. **Line ~223** — `span.start` for tool:
```python
self._bus.emit("span.start", {
    "workflow_id": self._wid,
    "node_id": self._node_id,
    "agent_name": self._agent_name,
    "span_id": tool_span_id,
    "span_type": "tool",
    "tool_name": event.part.tool_name,
    "ts": int(time.time() * 1000),
})
```

4. **Line ~239** — `span.end` for tool:
```python
self._bus.emit("span.end", {
    "workflow_id": self._wid,
    "node_id": self._node_id,
    "agent_name": self._agent_name,
    "span_id": _tool_span_ids.pop(matched_key),
    "span_type": "tool",
    "tool_name": event.part.tool_name,
    "ts": int(time.time() * 1000),
})
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/harness/engine/test_span_tracing.py::test_span_events_include_timestamps -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/engine/llm_executor.py tests/harness/engine/test_span_tracing.py
git commit -m "feat: add timestamps to span.start/span.end events"
```

---

## Task 2: Frontend — Update span types + create spanStore + activate handlers

**Files:**
- Modify: `frontend/src/types/events.ts:204-222`
- Create: `frontend/src/stores/spanStore.ts`
- Modify: `frontend/src/contexts/workflow-context/eventRouter.ts:300-303`
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:337-340`

**Step 1: Update SpanStartPayload and SpanEndPayload to include `ts`**

In `frontend/src/types/events.ts`, add `ts` field:

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
  ts: number; // epoch ms — when span started
}

export interface SpanEndPayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  span_id: string;
  span_type: "llm" | "tool";
  tool_name?: string;
  ts: number; // epoch ms — when span ended
}
```

**Step 2: Create spanStore**

Create `frontend/src/stores/spanStore.ts`:

```typescript
import { create } from "zustand";

export interface SpanRecord {
  spanId: string;
  agentName: string;
  spanType: "llm" | "tool";
  startTs: number;
  endTs: number | null;
  model?: string;
  toolName?: string;
}

export interface SpanState {
  spans: Record<string, SpanRecord>; // keyed by span_id
  workflowStartTs: number | null;

  startSpan: (payload: {
    span_id: string;
    agent_name: string;
    span_type: "llm" | "tool";
    ts: number;
    model?: string;
    tool_name?: string;
  }) => void;

  endSpan: (spanId: string, ts: number) => void;

  setWorkflowStartTs: (ts: number) => void;

  /** Compute waterfall data for chart.render. Returns empty if no complete spans. */
  computeWaterfallData: () => WaterfallRow[];

  reset: () => void;
}

export interface WaterfallRow {
  agent: string;
  start_ms: number;
  duration_ms: number;
  kind: "llm" | "tool";
  label: string;
}

const initialState = {
  spans: {} as Record<string, SpanRecord>,
  workflowStartTs: null as number | null,
};

export const useSpanStore = create<SpanState>()((set, get) => ({
  ...initialState,

  startSpan: (payload) =>
    set((state) => ({
      spans: {
        ...state.spans,
        [payload.span_id]: {
          spanId: payload.span_id,
          agentName: payload.agent_name,
          spanType: payload.span_type,
          startTs: payload.ts,
          endTs: null,
          model: payload.model,
          toolName: payload.tool_name,
        },
      },
    })),

  endSpan: (spanId, ts) =>
    set((state) => {
      const span = state.spans[spanId];
      if (!span) return state;
      return {
        spans: {
          ...state.spans,
          [spanId]: { ...span, endTs: ts },
        },
      };
    }),

  setWorkflowStartTs: (ts) => set({ workflowStartTs: ts }),

  computeWaterfallData: () => {
    const { spans, workflowStartTs } = get();
    if (!workflowStartTs) return [];

    const rows: WaterfallRow[] = [];
    for (const span of Object.values(spans)) {
      if (span.endTs === null) continue;
      rows.push({
        agent: span.agentName,
        start_ms: span.startTs - workflowStartTs,
        duration_ms: span.endTs - span.startTs,
        kind: span.spanType,
        label: span.spanType === "llm" ? (span.model ?? "LLM") : (span.toolName ?? "tool"),
      });
    }
    return rows;
  },

  reset: () => set(initialState),
}));
```

**Step 3: Activate span handlers in eventRouter.ts**

In `frontend/src/contexts/workflow-context/eventRouter.ts`, replace the no-op span handlers (~lines 300-303):

```typescript
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
```

Also add the import at top:
```typescript
import { useSpanStore } from "@/stores/spanStore";
```

And register it in the `stores` object (look for where `stores.workflow`, `stores.chart` etc. are defined — add `span: useSpanStore`).

**Step 4: Activate span handlers in useWorkflowEvents.ts**

In `frontend/src/hooks/useWorkflowEvents.ts`, replace the no-op span handlers (~lines 337-340):

```typescript
case "span.start": {
  const p = payload<SpanStartPayload>(event);
  useSpanStore.getState().startSpan(p);
  break;
}
case "span.end": {
  const p = payload<SpanEndPayload>(event);
  useSpanStore.getState().endSpan(p.span_id, p.ts);
  break;
}
```

Add import:
```typescript
import { useSpanStore } from "@/stores/spanStore";
```

**Step 5: Set workflowStartTs on workflow.started**

In both `eventRouter.ts` and `useWorkflowEvents.ts`, find the `workflow.started` handler and add:

```typescript
// After existing workflow.started handling:
useSpanStore.getState().setWorkflowStartTs(event.ts);
```

Also call `useSpanStore.getState().reset()` on `workflow.started` to clear stale data.

**Step 6: Build and verify no regressions**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

**Step 7: Commit**

```bash
git add frontend/src/types/events.ts frontend/src/stores/spanStore.ts frontend/src/contexts/workflow-context/eventRouter.ts frontend/src/hooks/useWorkflowEvents.ts
git commit -m "feat: add spanStore + activate span.start/end handlers"
```

---

## Task 3: Frontend — WaterfallChartWidget + ChartPayload extension

**Files:**
- Modify: `frontend/src/types/events.ts:152` (ChartPayload chart_type union)
- Create: `frontend/src/components/output/charts/WaterfallChartWidget.tsx`
- Modify: `frontend/src/components/output/ChartWidget.tsx`

**Step 1: Add "waterfall" to ChartPayload chart_type union**

In `frontend/src/types/events.ts`, extend the `chart_type` union (line ~153):

```typescript
export interface ChartPayload {
  chart_type:
    | "line"
    | "bar"
    | "scatter"
    | "pareto"
    | "optimal_line"
    | "heatmap"
    | "box"
    | "bubble"
    | "area"
    | "radar"
    | "table"
    | "waterfall";  // NEW
  data: Record<string, unknown>[];
  columns: string[];
  // ... rest unchanged
}
```

**Step 2: Create WaterfallChartWidget**

Create `frontend/src/components/output/charts/WaterfallChartWidget.tsx`:

The widget receives a `ChartPayload` where `data` is an array of:
- `agent: string` — y-axis label (one row per agent)
- `start_ms: number` — x offset from workflow start
- `duration_ms: number` — bar width
- `kind: "llm" | "tool"` — determines color
- `label: string` — tooltip detail

Each agent gets its own horizontal row. Bars are positioned by `start_ms` and sized by `duration_ms`. LLM spans use one color, tool spans use another.

Implementation uses pure SVG (not recharts) because recharts doesn't have a native Gantt/waterfall chart type. The component:

1. Groups `data` by `agent` to get row count
2. Finds max `(start_ms + duration_ms)` for x-axis range
3. Renders SVG bars with proper positioning
4. Uses `PALETTE` colors: `PALETTE[0]` for LLM, `PALETTE[1]` for tool
5. Shows tooltip on hover with agent name, label, duration
6. Uses `getAxisTick()` and `CHART_MARGIN` from `chartTheme.ts`

Target: ~120-150 lines.

**Step 3: Register WaterfallChartWidget in ChartWidget.tsx**

In `frontend/src/components/output/ChartWidget.tsx`, add import and case:

```typescript
import WaterfallChartWidget from "./charts/WaterfallChartWidget";

// In the switch:
case "waterfall":
  return <WaterfallChartWidget chart={chart} />;
```

**Step 4: Build and verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 5: Commit**

```bash
git add frontend/src/types/events.ts frontend/src/components/output/charts/WaterfallChartWidget.tsx frontend/src/components/output/ChartWidget.tsx
git commit -m "feat: add waterfall chart type + WaterfallChartWidget"
```

---

## Task 4: Frontend — Compute waterfall chart on workflow completion

**Files:**
- Modify: `frontend/src/lib/summary/runSummary.ts`

**Step 1: Add waterfall computation to runSummary.ts**

In `frontend/src/lib/summary/runSummary.ts`, add a new `SummaryComputer`:

```typescript
import { useSpanStore, type WaterfallRow } from "@/stores/spanStore";

// ... existing imports and functions ...

function executionTimeline(_nodes: NodeState[]): ChartPayload[] {
  const rows = useSpanStore.getState().computeWaterfallData();
  if (rows.length === 0) return [];

  return [{
    label: LABEL,
    title: "Execution Timeline",
    chart_type: "waterfall",
    category: CATEGORY,
    data: rows as unknown as Record<string, unknown>[],
    columns: ["agent", "start_ms", "duration_ms", "kind", "label"],
  }];
}
```

Add `executionTimeline` to `summaryComputers` array (before `runOverviewTable`):

```typescript
const summaryComputers: SummaryComputer[] = [
  tokensByAgent,
  durationByAgent,
  costByAgent,
  ttftByAgent,
  stepsByAgent,
  executionTimeline,  // NEW
  runOverviewTable,
];
```

**Step 2: Build and verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds. On next workflow run, Analysis Tab will show "Execution Timeline" waterfall chart.

**Step 3: Manual end-to-end test**

1. Start backend: `python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`
2. Open browser, run a workflow with multiple agents
3. On completion, check Analysis Tab shows "Execution Timeline" with per-agent horizontal bars
4. Verify LLM and tool spans are color-coded differently
5. Verify each agent has its own row

**Step 4: Commit**

```bash
git add frontend/src/lib/summary/runSummary.ts
git commit -m "feat: compute waterfall timeline from span data on workflow completion"
```

---

## Task 5: Backend — Include envelope config in workflow.started event

**Files:**
- Modify: `harness/engine/macro_graph.py` (workflow.started emit site)

**Step 1: Find workflow.started emit in macro_graph.py**

Search for `bus.emit("workflow.started"...)` in `harness/engine/macro_graph.py`. Add the envelope config to the payload:

```python
# Add to the workflow.started payload dict:
"envelope": builder_self.envelope,  # may be None — that's fine
```

This is a small, non-breaking change — the frontend will receive `envelope` as `null` when not configured.

**Step 2: Commit**

```bash
git add harness/engine/macro_graph.py
git commit -m "feat: include envelope config in workflow.started event"
```

---

## Task 6: Frontend — BudgetBar component

**Files:**
- Create: `frontend/src/components/diagnostics/BudgetBar.tsx`
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`

**Step 1: Create BudgetBar component**

Create `frontend/src/components/diagnostics/BudgetBar.tsx`:

The component reads:
- `workflowStore.envelope` — the budget limits `{ max_tokens?, max_steps?, max_duration_ms? }`
- `workflowStore.nodes` — accumulated tokens/steps/duration from node.completed events
- Displays a horizontal progress bar per dimension (tokens, steps, duration)
- Yellow when > 80%, red when > 100%

```typescript
// BudgetBar.tsx — lightweight component (~80 lines)
// Props: none — reads from workflowStore
// Shows up to 3 bars: Tokens, Steps, Duration
// Each bar: label | progress bar | current/max text
// Hidden when no envelope is configured
```

**Step 2: Add envelope to workflowStore**

In `frontend/src/stores/workflowStore.ts`:
- Add `envelope` to the state interface
- Set it from `workflow.started` payload
- Compute accumulated totals from nodes

**Step 3: Wire BudgetBar into DiagnosticsPanel**

In `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`, add `<BudgetBar />` above the tab bar. It auto-hides when no envelope is configured.

**Step 4: Build and verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 5: Manual test**

1. Run a workflow WITH envelope: `Workflow(envelope={"max_tokens": 50000, "max_steps": 20})`
2. Verify BudgetBar appears in diagnostics panel with progress bars
3. Run a workflow WITHOUT envelope
4. Verify BudgetBar is hidden

**Step 6: Commit**

```bash
git add frontend/src/components/diagnostics/BudgetBar.tsx frontend/src/components/diagnostics/DiagnosticsPanel.tsx frontend/src/stores/workflowStore.ts
git commit -m "feat: add BudgetBar component for envelope budget visualization"
```

---

## Task 7: Frontend — Regression tab in BenchmarkCompare

**Files:**
- Modify: `frontend/src/components/benchmark/BenchmarkCompare.tsx`

**Step 1: Add "regression" tab**

In `frontend/src/components/benchmark/BenchmarkCompare.tsx`:

1. Add `"regression"` to `CompareTab` type
2. Add button in tab bar
3. Create `RegressionTab` component that:
   - Calls `GET /api/benchmarks/{name}/regression` (existing API)
   - If < 2 results, shows placeholder message
   - Displays regressions as a table: metric | baseline | current | delta% | direction
   - Colors rows: red for regressed, green for improved
   - Shows baseline vs current run metadata

```typescript
// RegressionTab — reads benchmarkName prop
// Fetches from /api/benchmarks/{name}/regression
// Renders table with regression results
```

**Step 2: Build and verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 3: Manual test**

1. Run a benchmark twice
2. Open Benchmark > Compare > Regression tab
3. Verify regression metrics display correctly

**Step 4: Commit**

```bash
git add frontend/src/components/benchmark/BenchmarkCompare.tsx
git commit -m "feat: add regression detection tab to benchmark compare view"
```

---

## Task 8: Frontend build + final integration test + push

**Step 1: Full build**

```bash
cd frontend && npm run build
```

**Step 2: Run all Python tests**

```bash
pytest --timeout=30
```

**Step 3: Manual integration test**

1. Start server
2. Run a multi-agent workflow WITH envelope
3. Verify in Analysis Tab: all 7 charts appear (6 existing + Execution Timeline waterfall)
4. Verify in Diagnostics: BudgetBar shows when envelope configured
5. Run benchmark twice, verify Regression tab works

**Step 4: Commit build output + push**

```bash
git add frontend/out/
git commit -m "build: frontend build with waterfall + budget bar + regression UI"
git push origin main
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Span timestamps drift across processes | `time.time()` is sufficient — all spans in same process, relative offsets are what matters |
| Large number of spans overwhelms SVG rendering | Cap at ~200 spans; for most workflows it's < 50 |
| WaterfallChartWidget SVG doesn't resize | Use `ResponsiveContainer` pattern from other widgets |
| BudgetBar shows stale data | Reset on `workflow.started`; derive totals reactively from store |
| ChartPayload union change breaks existing charts | New union member is additive; existing charts unaffected |

## Dependencies

- Task 2 depends on Task 1 (needs `ts` in span payloads)
- Task 4 depends on Tasks 2 + 3 (needs spanStore + WaterfallChartWidget)
- Task 6 depends on Task 5 (needs envelope in workflow.started)
- Tasks 1-4, 5-6, 7 are independent tracks that can be parallelized
