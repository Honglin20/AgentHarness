# Unified Event Stream Architecture

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the dual Live/Replay data paths by making the event stream the single source of truth for all data — conversation, charts, and tool calls.

**Architecture:** Persist EventBus buffer events to run files. Frontend replay mode loads events and routes them through the same `eventRouter` → scoped stores → scoped components pipeline used by live mode. This unifies the rendering path and prevents ordering/formatting divergence between live and replay.

**Tech Stack:** Python (pytest), TypeScript/React (Zustand), Radix Collapsible

---

## Root Cause Summary

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Can't see live conversation | `handleClickRun` doesn't reset stores before switching | Reset stores + ensure WS reconnects |
| Messages grouped by type | `build_conversation()` iterates by agent, not by time | Use `ConversationCollector` (event-ordered) |
| Charts missing in results | Events not persisted; replay path doesn't populate stores | Persist events; replay through eventRouter |
| Collapsible stuck open | `onOpenChange` is no-op when `groupsProp` exists | Use local `useState` for collapse state |

---

## Phase 1: Backend — Event Stream Persistence

### Task 1: Add `events` field to RunStore

**Files:**
- Modify: `harness/run_store.py:28-68`
- Test: `tests/test_run_store.py`

**Step 1: Write the failing test**

Add to `tests/test_run_store.py`:

```python
def test_save_with_events(tmp_path):
    """RunStore.save() should persist the events list."""
    store = RunStore(str(tmp_path))
    events = [
        {"type": "agent.text_delta", "ts": 1000, "payload": {"text": "hello"}},
        {"type": "agent.tool_call", "ts": 1001, "payload": {"tool_name": "bash"}},
    ]
    store.save(
        run_id="evt-run-1",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        events=events,
    )
    loaded = store.get_run("evt-run-1")
    assert loaded is not None
    assert loaded["events"] == events


def test_get_run_without_events_backward_compat(tmp_path):
    """Existing runs without events field should load fine."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="old-run-1",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )
    loaded = store.get_run("old-run-1")
    assert loaded is not None
    assert "events" not in loaded
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_store.py::test_save_with_events tests/test_run_store.py::test_get_run_without_events_backward_compat -v`
Expected: `test_save_with_events` FAILS (unexpected keyword argument `events`)

**Step 3: Add `events` parameter to RunStore.save()**

Modify `harness/run_store.py` — add `events` parameter and persistence:

```python
def save(
    self,
    run_id: str,
    workflow_name: str,
    agents_snapshot: list[dict],
    status: str,
    inputs: dict,
    result: dict | None,
    dag: dict | None = None,
    agent_io: dict | None = None,
    batch_id: str | None = None,
    user_id: str | None = None,
    chart_groups: dict | None = None,
    conversation: list[dict] | None = None,
    events: list[dict] | None = None,
    created_at: str | None = None,
) -> Path:
    record = {
        "run_id": run_id,
        "workflow_name": workflow_name,
        "agents_snapshot": agents_snapshot,
        "status": status,
        "inputs": inputs,
        "result": result,
        "dag": dag,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
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
    path = self._safe_path(run_id)
    if path is None:
        raise ValueError(f"Invalid run_id: {run_id}")
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return path
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/run_store.py tests/test_run_store.py
git commit -m "feat: add events field to RunStore for event stream persistence"
```

---

### Task 2: Persist EventBus buffer in runner.py

**Files:**
- Modify: `server/runner.py:266-289` (completed handler)
- Modify: `server/runner.py:324-346` (failed handler)

**Step 1: Write the failing test**

Add to `tests/test_run_store.py`:

```python
def test_save_with_large_events_list(tmp_path):
    """Events list should persist even with 500+ events."""
    store = RunStore(str(tmp_path))
    events = [{"type": "agent.text_delta", "ts": i, "payload": {"text": f"chunk-{i}"}} for i in range(600)]
    store.save(
        run_id="large-evt-run",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        events=events,
    )
    loaded = store.get_run("large-evt-run")
    assert len(loaded["events"]) == 600
```

**Step 2: Run test to verify it passes** (should already pass after Task 1)

Run: `pytest tests/test_run_store.py::test_save_with_large_events_list -v`
Expected: PASS

**Step 3: Modify runner.py — completed handler**

Replace `build_conversation` with `ConversationCollector` and persist events:

In `server/runner.py`, at the completed handler (~line 265):

```python
from harness.extensions.collectors import ConversationCollector, ChartCollector

_agent_io = workflow._builder.agent_io if workflow._builder else {}
data = repo.get(workflow_id)
event_bus = data.get("event_bus") if data else None

# Collect conversation from event stream (time-ordered, not agent-grouped)
conv_collector = ConversationCollector(event_bus) if event_bus else None
if conv_collector:
    conv_collector.collect_from_buffer()
conversation = conv_collector.get_messages() if conv_collector else []

# Collect charts from event stream
chart_collector = ChartCollector(event_bus) if event_bus else None
chart_groups = chart_collector.get_chart_groups() if chart_collector else {}
if not chart_groups.get("groupOrder"):
    chart_groups = None

# Persist event stream for frontend replay
events = list(event_bus.buffer) if event_bus else []

RunStore().save(
    run_id=workflow_id,
    workflow_name=workflow.name,
    agents_snapshot=...,
    status="completed",
    inputs=inputs,
    result=...,
    dag=repo.get_dag(workflow_id),
    agent_io=_agent_io,
    batch_id=batch_id,
    user_id=user_id,
    conversation=conversation,
    chart_groups=chart_groups,
    events=events,
    created_at=...,
)
```

Do the same for the failed handler (~line 324).

**Step 4: Remove `build_conversation` import and usage**

In `server/runner.py`, remove:
```python
from harness.extensions.collectors import build_conversation, ChartCollector
```

Replace with:
```python
from harness.extensions.collectors import ConversationCollector, ChartCollector
```

Remove all `build_conversation(_agent_io)` calls.

**Step 5: Run existing tests**

Run: `pytest tests/ -v --ignore=tests/test_real_api.py --ignore=tests/test_phase2_integration.py -x`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add server/runner.py
git commit -m "refactor: replace build_conversation with ConversationCollector for correct event ordering"
```

---

### Task 3: Add ConversationCollector integration test

**Files:**
- Test: `tests/harness/extensions/test_collectors.py`

**Step 1: Write integration test**

Add to `tests/harness/extensions/test_collectors.py`:

```python
class TestConversationCollectorIntegration:
    """Verify ConversationCollector produces correctly ordered output
    matching the frontend's expected ConversationMessage structure."""

    def test_interleaved_text_and_tool_calls(self):
        """Agent text → tool call → tool result → more text should be in that order."""
        bus = FakeBus([
            {"type": "node.started", "ts": 1, "payload": {"node_id": "analyzer", "agent_name": "analyzer"}},
            {"type": "agent.text_delta", "ts": 2, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "text": "Starting analysis..."}},
            {"type": "agent.tool_call", "ts": 3, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "tool_name": "bash", "tool_args": {"command": "ls"}}},
            {"type": "agent.tool_result", "ts": 4, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "tool_name": "bash", "result": "file1.py\nfile2.py"}},
            {"type": "agent.text_delta", "ts": 5, "payload": {"node_id": "analyzer", "agent_name": "analyzer", "text": "Found 2 files."}},
            {"type": "node.completed", "ts": 6, "payload": {"node_id": "analyzer", "agent_name": "analyzer"}},
        ])

        collector = ConversationCollector(bus)
        collector.collect_from_buffer()
        messages = collector.get_messages()

        # Should have: agent text, tool_call, agent text (3 messages)
        assert len(messages) == 3

        # Order must be: text → tool → text (NOT text+text → tool)
        assert messages[0]["type"] == "agent"
        assert messages[0]["content"] == "Starting analysis..."
        assert messages[1]["type"] == "tool_call"
        assert messages[1]["toolName"] == "bash"
        assert messages[2]["type"] == "agent"
        assert messages[2]["content"] == "Found 2 files."

    def test_multi_agent_ordering(self):
        """Events from different agents should be interleaved by timestamp."""
        bus = FakeBus([
            {"type": "node.started", "ts": 1, "payload": {"node_id": "a1", "agent_name": "a1"}},
            {"type": "agent.text_delta", "ts": 2, "payload": {"node_id": "a1", "text": "A1 text"}},
            {"type": "node.completed", "ts": 3, "payload": {"node_id": "a1", "agent_name": "a1"}},
            {"type": "node.started", "ts": 4, "payload": {"node_id": "a2", "agent_name": "a2"}},
            {"type": "agent.text_delta", "ts": 5, "payload": {"node_id": "a2", "text": "A2 text"}},
            {"type": "node.completed", "ts": 6, "payload": {"node_id": "a2", "agent_name": "a2"}},
        ])

        collector = ConversationCollector(bus)
        collector.collect_from_buffer()
        messages = collector.get_messages()

        assert len(messages) == 2
        assert messages[0]["agentName"] == "a1"
        assert messages[1]["agentName"] == "a2"


class FakeBus:
    """Minimal Bus mock with a readable buffer."""
    def __init__(self, events):
        self.buffer = events
```

**Step 2: Run test**

Run: `pytest tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/harness/extensions/test_collectors.py
git commit -m "test: add ConversationCollector integration tests for event ordering"
```

---

### Task 4: Increase EventBus buffer size for robustness

**Files:**
- Modify: `harness/extensions/bus.py:65`

**Step 1: Increase default buffer to 2000**

In `harness/extensions/bus.py`, change:

```python
def __init__(self, buffer_size: int = 500):
```

to:

```python
def __init__(self, buffer_size: int = 2000):
```

**Step 2: Run bus tests**

Run: `pytest harness/extensions/test_bus.py tests/server/test_event_bus.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add harness/extensions/bus.py
git commit -m "perf: increase EventBus buffer to 2000 for long workflows"
```

---

## Phase 2: Frontend — Unified Event Replay

### Task 5: Add `replayEventsToStores` utility

**Files:**
- Create: `frontend/src/contexts/workflow-context/replayEvents.ts`
- Test: manual verification (no frontend test infra)

**Step 1: Create the replay utility**

Create `frontend/src/contexts/workflow-context/replayEvents.ts`:

```typescript
/**
 * Replay persisted events into scoped workflow stores.
 *
 * This is the bridge between "run completed" data and the live rendering path.
 * By routing persisted events through routeEventToStores(), replay mode uses
 * the exact same store population logic as live mode.
 */
import type { WSEvent } from "@/types/events";
import { getWorkflowManager } from "./WorkflowManager";
import { getToolCallCounter } from "./workflowStores";

/**
 * Replay an array of persisted events into the scoped stores for a workflow.
 *
 * Call this BEFORE rendering scoped components so stores are pre-populated.
 * The events array comes from run.events in the run JSON file.
 */
export function replayEventsToStores(
  workflowId: string,
  events: WSEvent[],
): void {
  const manager = getWorkflowManager();
  const stores = manager.getStores(workflowId);
  if (!stores) {
    console.warn(`[replayEvents] No stores found for ${workflowId}`);
    return;
  }

  // Reset all stores to clean state before replay
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();

  // Reset tool call counter for this store
  const counter = getToolCallCounter(stores.toolCall);

  // Route each event through the same path as live mode
  for (const event of events) {
    routeReplayEvent(stores, event, counter);
  }
}

/**
 * Subset of routeEventToStores from eventRouter.ts
 * that handles conversation/chart-relevant events.
 *
 * Intentionally does NOT handle lifecycle events (workflow.started/completed)
 * since those trigger side effects like API calls.
 */
function routeReplayEvent(
  stores: import("./workflowStores").WorkflowStores,
  event: WSEvent,
  counter: ReturnType<typeof getToolCallCounter>,
): void {
  const p = event.payload ?? {};

  switch (event.type) {
    case "node.started": {
      stores.workflow.getState().handleNodeStarted(p as any);
      stores.output.getState().setActiveNode((p as any).node_id);
      stores.conversation.getState().addAgentMessage((p as any).node_id, (p as any).agent_name);
      break;
    }

    case "node.completed": {
      stores.workflow.getState().handleNodeCompleted(p as any);
      const nodeP = p as any;
      // Format output into message content if available
      if (nodeP.output_result) {
        const convState = stores.conversation.getState();
        const idx = convState.messages.findLastIndex(
          (m) => m.nodeId === nodeP.node_id && m.type === "agent" && (m.status === "streaming" || m.status === "done"),
        );
        if (idx !== -1 && !convState.messages[idx].content.trim()) {
          const formatted = formatOutputAsMd(nodeP.output_result);
          stores.conversation.setState((state) => {
            const messages = [...state.messages];
            messages[idx] = { ...messages[idx], content: formatted };
            return { messages };
          });
        }
      }
      stores.conversation.getState().completeAgentMessage(nodeP.node_id, nodeP.agent_name, nodeP.duration_ms);
      if (nodeP.input_prompt || nodeP.output_result || nodeP.system_prompt) {
        stores.agentIO.getState().setAgentIO(nodeP.node_id, nodeP.input_prompt ?? "", nodeP.output_result, nodeP.system_prompt);
      }
      break;
    }

    case "node.failed": {
      stores.workflow.getState().handleNodeFailed(p as any);
      stores.conversation.getState().failAgentMessage((p as any).node_id, (p as any).agent_name, (p as any).error, (p as any).duration_ms);
      break;
    }

    case "agent.text_delta": {
      const textP = p as any;
      stores.output.getState().appendText(textP.node_id, textP.text);
      stores.conversation.getState().appendAgentText(textP.node_id, textP.text);
      break;
    }

    case "agent.tool_call": {
      const tcP = p as any;
      const id = counter.next();
      stores.toolCall.getState().addToolCall(id, tcP.node_id, tcP.agent_name, tcP.tool_name, tcP.tool_args || {});
      stores.conversation.getState().addToolCall(tcP.node_id, tcP.agent_name, tcP.tool_name, tcP.tool_args || {});
      break;
    }

    case "agent.tool_result": {
      const trP = p as any;
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find((r) => r.nodeId === trP.node_id && r.toolName === trP.tool_name && r.result === undefined);
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(trP.result ?? ""));
      }
      stores.conversation.getState().addToolResult(trP.node_id, trP.tool_name, String(trP.result ?? ""));
      break;
    }

    case "agent.tool_output_delta": {
      const odP = p as any;
      stores.conversation.getState().appendToolOutput(odP.node_id, odP.tool_name, odP.line, odP.stream);
      break;
    }

    case "chat.question": {
      const qP = p as any;
      stores.chat.getState().addAgentQuestion(qP.question_id, qP.question);
      const conv = stores.conversation.getState();
      const lastStreaming = [...conv.messages].reverse().find((m) => m.type === "agent" && m.status === "streaming");
      const agentName = lastStreaming?.agentName ?? "agent";
      conv.addAgentQuestion(qP.question_id, qP.question, agentName);
      break;
    }

    case "chat.answer": {
      const aP = p as any;
      stores.conversation.getState().addUserMessage(aP.answer ?? "");
      break;
    }

    case "chart.render": {
      const cP = p as any;
      stores.chart.getState().addChart(cP.chart);
      break;
    }
  }
}

/** Format output value as markdown (mirrors eventRouter.ts implementation). */
function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") {
    try {
      const parsed = JSON.parse(output);
      return formatOutputAsMd(parsed);
    } catch {
      return output;
    }
  }
  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    if (obj.summary) lines.push(String(obj.summary));
    if (obj.details) lines.push("", String(obj.details));
    const extra = Object.entries(obj).filter(([k]) => k !== "summary" && k !== "details");
    if (extra.length > 0) {
      lines.push("", "| Field | Value |", "|-------|-------|");
      for (const [k, v] of extra) {
        const val = typeof v === "object" ? JSON.stringify(v) : String(v);
        lines.push(`| ${k} | ${val} |`);
      }
    }
    if (lines.length > 0) return lines.join("\n");
  }
  return JSON.stringify(output, null, 2);
}
```

**Step 2: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts
git commit -m "feat: add replayEventsToStores utility for unified event replay"
```

---

### Task 6: Update viewStore to replay events into scoped stores

**Files:**
- Modify: `frontend/src/stores/viewStore.ts`
- Modify: `frontend/src/contexts/workflow-context/WorkflowManager.ts`

**Step 1: Update viewStore.showReplay() to trigger event replay**

Modify `frontend/src/stores/viewStore.ts`:

```typescript
import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores } from "@/contexts/workflow-context/replayEvents";

export type ActiveView =
  | { type: "live" }
  | { type: "replay"; runId: string; run: RunRecord };

interface ViewState {
  activeView: ActiveView;
  showLive: () => void;
  showReplay: (run: RunRecord) => void;
}

export const useViewStore = create<ViewState>()((set) => ({
  activeView: { type: "live" },
  showLive: () => set({ activeView: { type: "live" } }),
  showReplay: (run) => {
    // Populate agentIOStore from persisted run data (backward compat)
    if (run.agent_io) {
      const store = useAgentIOStore.getState();
      for (const [nodeId, io] of Object.entries(run.agent_io)) {
        store.setAgentIO(nodeId, io.input_prompt ?? "", io.output_result, io.system_prompt);
      }
    }

    // If run has persisted events, replay them into scoped stores
    // This is the new unified path
    if (run.events && run.events.length > 0) {
      const manager = getWorkflowManager();
      const entry = manager.getOrCreate(run.run_id);
      replayEventsToStores(run.run_id, run.events);
    }

    set({ activeView: { type: "replay", runId: run.run_id, run } });
  },
}));
```

**Step 2: Add `getOrCreate` method to WorkflowManager if not exists**

Check `frontend/src/contexts/workflow-context/WorkflowManager.ts` for `getOrCreate` method. It should already exist (used by WorkflowScope). If it does, skip this step.

**Step 3: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "feat: replay persisted events into scoped stores on showReplay"
```

---

### Task 7: Unify WorkflowCenterPanel — replay uses scoped architecture

**Files:**
- Modify: `frontend/src/components/layout/WorkflowCenterPanel.tsx`
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx`

**Step 1: Update WorkflowCenterPanel to use scoped architecture for replay**

Modify `frontend/src/components/layout/WorkflowCenterPanel.tsx`:

```typescript
"use client";

import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowScope, WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
import { useWorkflowWS } from "@/contexts/workflow-context/useWorkflowWS";
import { ScopedCenterPanel } from "./ScopedCenterPanel";

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Replay mode: use the replay run's ID (stores already populated by viewStore)
  if (activeView.type === "replay") {
    return activeView.runId;
  }

  // Batch mode: only enter Context path when a run is explicitly selected
  if (activeBatchId) {
    return selectedRunId;
  }

  // Normal mode: use the global workflowId
  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();

  // WebSocket managed at this stable level — survives workflow switches
  // For replay mode, we don't connect WebSocket (no live events to receive)
  const activeView = useViewStore((s) => s.activeView);
  const isReplay = activeView.type === "replay";
  const wsMethods = useWorkflowWS(isReplay ? null : workflowId);

  // No workflow active at all: show landing page via ScopedCenterPanel
  if (!workflowId) {
    return (
      <WorkflowScope workflowId={null}>
        <ScopedCenterPanel activeBenchmark={activeBenchmark} />
      </WorkflowScope>
    );
  }

  // Context architecture: scoped stores for both live and replay
  const wsProvider = isReplay ? (
    <>{undefined}</>
  ) : (
    <WSMethodProvider
      sendAnswer={wsMethods.sendAnswer}
      sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
    >
      <ScopedCenterPanel activeBenchmark={activeBenchmark} />
    </WSMethodProvider>
  );

  return (
    <WorkflowScope workflowId={workflowId}>
      {isReplay ? (
        <ScopedCenterPanel activeBenchmark={activeBenchmark} isReplay />
      ) : (
        <WSMethodProvider
          sendAnswer={wsMethods.sendAnswer}
          sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
        >
          <ScopedCenterPanel activeBenchmark={activeBenchmark} />
        </WSMethodProvider>
      )}
    </WorkflowScope>
  );
}
```

**Step 2: Simplify ScopedCenterPanel — remove isReplay branching for conversation/results**

Modify `frontend/src/components/layout/ScopedCenterPanel.tsx`:

Key changes:
1. Add `isReplay` prop (from parent)
2. Remove `replayMessages` derivation — always read from scoped conversation store
3. Always use `ScopedConversationTab` / `ScopedResultsTab` / `ScopedAnalysisTab`
4. Keep `isReplay` only for: hiding ChatInput, showing REPLAY badge, disabling auto-scroll

The `ScopedConversationTab` already reads from scoped stores. If events were replayed (Task 6), the stores are populated. If not (backward compat), stores are empty but `conversation` field is available as fallback.

```typescript
// REMOVE this block:
const replayMessages: ConversationMessage[] | undefined = (() => {
  if (activeView.type !== "replay") return undefined;
  const raw = activeView.run.conversation ?? [];
  return raw.map((m, i) => ({ ... }));
})();

// REPLACE conversation tab rendering:
// OLD: isReplay ? <ConversationTab messages={replayMessages} autoScroll={false} /> : <ScopedConversationTab />
// NEW: <ScopedConversationTab />
// (stores are already populated by replayEventsToStores)

// REPLACE results tab rendering:
// OLD: isReplay ? <ResultsTab groups={...} groupOrder={...} /> : <ScopedResultsTab />
// NEW: <ScopedResultsTab />
// (stores are already populated by replayEventsToStores)

// REPLACE analysis tab rendering:
// OLD: isReplay ? <AnalysisTab groups={...} groupOrder={...} /> : <ScopedAnalysisTab />
// NEW: <ScopedAnalysisTab />
```

**Step 3: Commit**

```bash
git add frontend/src/components/layout/WorkflowCenterPanel.tsx frontend/src/components/layout/ScopedCenterPanel.tsx
git commit -m "refactor: unify live/replay rendering through scoped stores"
```

---

### Task 8: Add fallback for runs without events (backward compat)

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts`

**Step 1: Add fallback that loads conversation/chart_groups directly**

In `replayEvents.ts`, add a fallback function:

```typescript
/**
 * Fallback for old runs that don't have persisted events.
 * Loads conversation and chart_groups directly into stores.
 */
export function loadLegacyRunData(
  workflowId: string,
  conversation: any[],
  chartGroups: { groups: Record<string, any>; groupOrder: string[] } | null,
): void {
  const manager = getWorkflowManager();
  const stores = manager.getStores(workflowId);
  if (!stores) return;

  // Reset stores
  stores.conversation.getState().reset();
  stores.chart.getState().reset();

  // Load conversation messages directly
  if (conversation && conversation.length > 0) {
    const messages = conversation.map((m, i) => ({
      id: m.id ?? `legacy-${i}`,
      type: m.type as ConversationMessage["type"],
      content: m.content ?? "",
      agentName: m.agentName,
      toolName: m.toolName,
      toolArgs: m.toolArgs,
      toolResult: m.toolResult,
      status: (m.status as ConversationMessage["status"]) ?? "done",
      durationMs: m.durationMs,
      timestamp: m.timestamp ?? 0,
    }));
    stores.conversation.setState({ messages });
  }

  // Load chart groups directly
  if (chartGroups?.groupOrder?.length) {
    for (const label of chartGroups.groupOrder) {
      const group = chartGroups.groups[label];
      if (group) {
        stores.chart.getState().addChartGroup(label, group);
      }
    }
  }
}
```

**Step 2: Update viewStore to use fallback**

In `frontend/src/stores/viewStore.ts`, update `showReplay`:

```typescript
showReplay: (run) => {
  // ... existing agent_io population ...

  if (run.events && run.events.length > 0) {
    // New path: replay events into stores
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);
    replayEventsToStores(run.run_id, run.events);
  } else {
    // Backward compat: load legacy data directly
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);
    loadLegacyRunData(run.run_id, run.conversation ?? [], run.chart_groups ?? null);
  }

  set({ activeView: { type: "replay", runId: run.run_id, run } });
},
```

**Step 3: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts frontend/src/stores/viewStore.ts
git commit -m "feat: add backward-compatible fallback for runs without events"
```

---

## Phase 3: UI Fixes

### Task 9: Fix Collapsible — use local state for replay mode

**Files:**
- Modify: `frontend/src/components/results/ResultsTab.tsx`
- Modify: `frontend/src/components/results/ScopedResultsTab.tsx`
- Modify: `frontend/src/components/analysis/AnalysisTab.tsx`
- Modify: `frontend/src/components/analysis/ScopedAnalysisTab.tsx`

**Step 1: Fix ResultsTab.tsx**

The current code:
```tsx
<Collapsible
  open={!group.collapsed}
  onOpenChange={() => { if (!groupsProp) toggleCollapse(label); }}
>
```

The problem: when `groupsProp` is provided, `onOpenChange` is a no-op, so the Collapsible never changes state.

Fix: use local `useState` to track collapsed state:

```tsx
export default function ResultsTab({ groups: groupsProp, groupOrder: groupOrderProp }: ResultsTabProps = {}) {
  const storeGroups = useChartStore((s) => s.groups);
  const storeGroupOrder = useChartStore((s) => s.groupOrder);
  const toggleCollapse = useChartStore((s) => s.toggleCollapse);

  // Local collapse state for replay mode (when groupsProp is provided)
  const [localCollapsed, setLocalCollapsed] = useState<Record<string, boolean>>({});

  const raw = groupsProp
    ? filterGroupsByCategory(groupsProp, groupOrderProp ?? [], null)
    : filterGroupsByCategory(storeGroups, storeGroupOrder, null);

  const groups = raw.groups;
  const groupOrder = raw.order;

  if (groupOrder.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <p className="text-center text-sm text-muted-foreground">
          No results yet. Results will appear here when agents produce charts or
          tables.
        </p>
      </div>
    );
  }

  const isReplay = !!groupsProp;

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        {groupOrder.map((label) => {
          const group = groups[label];
          if (!group) return null;

          const chartEntries = Object.values(group.charts);
          const itemCount = chartEntries.length + (group.table ? 1 : 0);
          if (itemCount === 0) return null;

          const collapsed = isReplay
            ? (localCollapsed[label] ?? group.collapsed)
            : group.collapsed;

          return (
            <div key={label} className="border border-app-border rounded-lg mb-3">
              <Collapsible
                open={!collapsed}
                onOpenChange={() => {
                  if (isReplay) {
                    setLocalCollapsed((prev) => ({ ...prev, [label]: !collapsed }));
                  } else {
                    toggleCollapse(label);
                  }
                }}
              >
                <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-app-bg-secondary rounded-t-lg">
                  {collapsed ? (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium text-app-text-primary">{label}</span>
                  <span className="text-xs text-muted-foreground">
                    {itemCount} {itemCount === 1 ? "item" : "items"}
                  </span>
                </CollapsibleTrigger>

                <CollapsibleContent>
                  {/* ... existing chart rendering ... */}
                </CollapsibleContent>
              </Collapsible>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
```

**Step 2: Apply the same fix to ScopedResultsTab.tsx, AnalysisTab.tsx, ScopedAnalysisTab.tsx**

Same pattern: add `localCollapsed` state, use it when `groupsProp` is provided.

**Step 3: Commit**

```bash
git add frontend/src/components/results/ResultsTab.tsx frontend/src/components/results/ScopedResultsTab.tsx frontend/src/components/analysis/AnalysisTab.tsx frontend/src/components/analysis/ScopedAnalysisTab.tsx
git commit -m "fix: Collapsible toggle works in both live and replay modes"
```

---

### Task 10: Fix live view switching — reset stores on workflow switch

**Files:**
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx`

**Step 1: Ensure stores are reset when clicking into a running workflow**

In `RunHistoryList.tsx`, the `handleClickRun` for running workflows should reset stores:

```typescript
const handleClickRun = async (run: RunRecord) => {
  onLeaveBenchmark?.();
  selectRun(run.run_id);
  if (run.status === "running") {
    // Switch to live view for this running workflow
    setActiveWorkflowId(run.run_id);
    setWorkflow(run.run_id, run.workflow_name, null);
    showLive();
    return;
  }
  const full = await fetchRun(run.run_id);
  if (full) showReplay(full);
};
```

The `setActiveWorkflowId` in the legacy path already clears conversation messages. The scoped path should also reset — verify that `WorkflowManager.setActiveWorkflowId` handles this correctly. If not, add store resets.

**Step 2: Commit** (if changes were needed)

```bash
git add frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "fix: ensure stores reset when switching to running workflow"
```

---

## Phase 4: Cleanup & Robustness

### Task 11: Update frontend RunRecord type

**Files:**
- Modify: `frontend/src/stores/runHistoryStore.ts`

**Step 1: Add `events` field to RunRecord**

```typescript
export interface RunRecord {
  // ... existing fields ...
  events?: Array<{
    type: string;
    ts: number;
    payload: Record<string, unknown>;
  }>;
}
```

**Step 2: Commit**

```bash
git add frontend/src/stores/runHistoryStore.ts
git commit -m "feat: add events field to frontend RunRecord type"
```

---

### Task 12: Handle ConversationCollector edge case — no EventBus

**Files:**
- Modify: `server/runner.py`

**Step 1: Add fallback when event_bus is None**

In runner.py, the completed/failed handlers should handle the case where `event_bus` is None (e.g., workflow ran without server):

```python
event_bus = data.get("event_bus") if data else None

# Collect conversation from events, fallback to build_conversation
if event_bus:
    conv_collector = ConversationCollector(event_bus)
    conv_collector.collect_from_buffer()
    conversation = conv_collector.get_messages()
    events = list(event_bus.buffer)
else:
    # Fallback: use agent_io-based conversation (old behavior)
    from harness.extensions.collectors import build_conversation as _build_conv
    conversation = _build_conv(_agent_io)
    events = []
```

**Step 2: Commit**

```bash
git add server/runner.py
git commit -m "fix: handle missing EventBus with fallback to build_conversation"
```

---

### Task 13: Build frontend and smoke test

**Step 1: Build frontend**

```bash
cd frontend && npm run build
```

**Step 2: Start server and run chart demo workflow**

```bash
bash examples/launch_ui.sh
```

Manual verification checklist:
1. [ ] Start a workflow → conversation streams in real-time
2. [ ] While running, click the run in sidebar → conversation shows current state
3. [ ] After completion, click the run → conversation shows correct interleaved order (text → tool → text)
4. [ ] Results tab shows charts
5. [ ] Click chart group header → collapses/expands
6. [ ] Click a different completed run → shows that run's data
7. [ ] Click back to live → shows current workflow state

**Step 3: Commit build artifacts**

```bash
git add frontend/out/
git commit -m "build: deploy frontend with unified event stream architecture"
```

---

## Summary of Changes

| Layer | File | Change |
|-------|------|--------|
| **Backend** | `harness/run_store.py` | Add `events` parameter to `save()` |
| **Backend** | `server/runner.py` | Use `ConversationCollector` instead of `build_conversation()`, persist events |
| **Backend** | `harness/extensions/bus.py` | Increase buffer from 500 → 2000 |
| **Frontend** | `contexts/workflow-context/replayEvents.ts` | NEW: Event replay utility |
| **Frontend** | `stores/viewStore.ts` | Replay events into scoped stores on `showReplay()` |
| **Frontend** | `components/layout/WorkflowCenterPanel.tsx` | Use scoped architecture for replay mode |
| **Frontend** | `components/layout/ScopedCenterPanel.tsx` | Remove isReplay component branching |
| **Frontend** | `components/results/ResultsTab.tsx` | Fix Collapsible with local state |
| **Frontend** | `components/results/ScopedResultsTab.tsx` | Fix Collapsible with local state |
| **Frontend** | `components/analysis/AnalysisTab.tsx` | Fix Collapsible with local state |
| **Frontend** | `components/analysis/ScopedAnalysisTab.tsx` | Fix Collapsible with local state |
| **Frontend** | `stores/runHistoryStore.ts` | Add `events` field to RunRecord |
| **Tests** | `tests/test_run_store.py` | Events persistence tests |
| **Tests** | `tests/harness/extensions/test_collectors.py` | ConversationCollector integration tests |

---

## Architecture After Changes

```
┌──────────────────────────────────────────────────┐
│                   RUN FILE                        │
│  { events: [...], conversation: [...],            │
│    chart_groups: {...}, agent_io: {...} }         │
│         │              │                           │
│         │ events       │ conversation (fallback)  │
│         ▼              ▼                           │
│  replayEvents()  loadLegacyRunData()              │
│         │              │                           │
│         └──────┬───────┘                           │
│                ▼                                   │
│         SCOPED STORES                              │
│  (conversation, chart, toolCall, ...)             │
│                │                                   │
│                ▼                                   │
│    SAME SCOPED COMPONENTS                         │
│  (ScopedConversationTab, ScopedResultsTab, ...)   │
│                                                   │
│  ═══ For LIVE mode: ═══                           │
│  WebSocket → eventRouter → same scoped stores     │
│                                                   │
│  ═══ For REPLAY mode: ═══                         │
│  Persisted events → replayEvents → same stores    │
└──────────────────────────────────────────────────┘
```

One data path into stores, one rendering path out of stores.
