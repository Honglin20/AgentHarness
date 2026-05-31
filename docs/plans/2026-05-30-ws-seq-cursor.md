# WS Seq Cursor — Fix Historical Run Fidelity & Conversation Stacking

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clicking any historical or running workflow shows identical UI to a live run — conversation, DAG, analysis charts, tools, agentIO all present and correct, with no stacking on switch.

**Architecture:** Add monotonically-increasing `seq` to every Bus event. Backend `subscribe(since_seq)` replays events after that cursor. Frontend resets scoped stores on workflow switch and connects WS with `since_seq=0` to get full replay from the server — one authoritative path for both live and completed runs. Completed runs reconstruct a read-only Bus from persisted events.

**Tech Stack:** Python (asyncio/FastAPI), TypeScript (React/Zustand)

---

## Root Cause (recap)

| Symptom | Mechanism |
|---------|-----------|
| Conversation stacking on switch | `Bus.subscribe()` auto-replays buffer → scoped store appends → no reset on switch → each reconnect doubles messages |
| Completed run shows empty panels | Bus is GC'd after workflow finishes → WS connects to empty Bus → REST fallback is racy |
| loadLegacyRunData partial reset | Only resets 3 of 8 stores → toolCall/agentIO/chat/span carry stale data |
| Dual store systems | Legacy global stores + scoped stores managed by different switch paths |

---

### Task 1: Add `seq` to Bus events

**Files:**
- Modify: `harness/extensions/bus.py:65-156`
- Test: `tests/server/test_event_bus.py`

**Why:** Every event needs a monotonically-increasing sequence number so clients can request replay from any cursor position.

**Step 1: Write the failing test**

Add to `tests/server/test_event_bus.py`:

```python
@pytest.mark.asyncio
async def test_emit_assigns_monotonic_seq():
    """emit() assigns seq 1, 2, 3... to successive events."""
    bus = Bus()
    bus.emit("test.event", {"a": 1})
    bus.emit("test.event", {"b": 2})
    bus.emit("test.event", {"c": 3})
    buf = bus.buffer
    assert [e["seq"] for e in buf] == [1, 2, 3]


@pytest.mark.asyncio
async def test_subscribe_since_seq():
    """subscribe(since_seq=N) only replays events with seq > N."""
    bus = Bus()
    bus.emit("test.event", {"i": 1})  # seq=1
    bus.emit("test.event", {"i": 2})  # seq=2
    bus.emit("test.event", {"i": 3})  # seq=3

    # Subscribe from seq=2 → should only get event with seq=3
    sub_id, queue = await bus.subscribe(since_seq=2)
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert len(events) == 1
    assert events[0]["seq"] == 3
    assert events[0]["payload"]["i"] == 3

    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_subscribe_since_seq_default_replays_all():
    """subscribe() with no since_seq replays entire buffer (backward compat)."""
    bus = Bus()
    bus.emit("test.event", {"i": 1})
    bus.emit("test.event", {"i": 2})

    sub_id, queue = await bus.subscribe()
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert len(events) == 2

    await bus.unsubscribe(sub_id)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_event_bus.py::test_emit_assigns_monotonic_seq tests/server/test_event_bus.py::test_subscribe_since_seq tests/server/test_event_bus.py::test_subscribe_since_seq_default_replays_all -v`
Expected: FAIL — `Bus.__init__` has no `_seq`, `subscribe` has no `since_seq` param, events have no `seq` field.

**Step 3: Implement `seq` in Bus**

Modify `harness/extensions/bus.py`:

```python
class Bus:
    def __init__(self, buffer_size: int = 2000):
        # WS subscribers
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size

        # Monotonic sequence counter
        self._seq: int = 0

        # Extensions
        self._hooks: dict[str, BaseHook] = {}
        self._middleware: dict[str, BaseMiddleware] = {}
        self._mutators: dict[str, BaseGraphMutator] = {}

        # User context
        self._user_context: dict[str, Any] = {}

    # ----- subscribe with cursor -----

    async def subscribe(self, since_seq: int | None = None) -> tuple[str, asyncio.Queue]:
        async with self._lock:
            sub_id = str(uuid.uuid4())
            queue: asyncio.Queue[dict] = asyncio.Queue()
            self._subscribers[sub_id] = queue
            # Replay buffer: all events if since_seq is None, else events with seq > since_seq
            for event in self._buffer:
                if since_seq is not None and event.get("seq", 0) <= since_seq:
                    continue
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"Queue full during replay for {sub_id}")
                    break
            return sub_id, queue

    # ----- emit with seq -----

    def emit(self, event_type: str, payload: dict) -> None:
        payload = dict(payload)
        if "user_id" not in payload and self._user_context.get("user_id"):
            payload["user_id"] = self._user_context["user_id"]

        self._seq += 1
        event = {"type": event_type, "ts": _now(), "seq": self._seq, "payload": payload}
        self._buffer.append(event)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size:]
        for sub_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"Queue full for {sub_id}; dropping event")
            except Exception as e:
                logger.error(f"Error emitting to {sub_id}: {e}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_event_bus.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `pytest tests/server/ -v`
Expected: ALL PASS (backward compat: `subscribe()` with no args still replays all)

**Step 6: Commit**

```bash
git add harness/extensions/bus.py tests/server/test_event_bus.py
git commit -m "feat: add monotonic seq to Bus events + subscribe(since_seq) cursor"
```

---

### Task 2: WS endpoint accepts `since_seq` query param

**Files:**
- Modify: `server/ws_handler.py:250-307`
- Test: `tests/server/test_ws_handler.py`

**Why:** Frontend needs to request replay from a specific cursor when connecting to a workflow's WS. For a fresh view, `since_seq=0` gives full replay. For reconnect after disconnect, `since_seq=lastSeenSeq` gives only missed events.

**Step 1: Write the failing test**

Add to `tests/server/test_ws_handler.py`:

```python
@pytest.mark.asyncio
async def test_ws_since_seq_param():
    """WS endpoint passes since_seq to Bus.subscribe."""
    from harness.extensions.bus import Bus
    bus = Bus()
    bus.emit("test.event", {"i": 1})  # seq=1
    bus.emit("test.event", {"i": 2})  # seq=2

    repo = get_repository()
    repo.put("test-wf-seq", {"event_bus": bus, "status": "running"})

    # Connect with since_seq=1 → should only get seq=2
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.websocket_connect("/ws/workflows/test-wf-seq?user_id=test&since_seq=1") as ws:
            # Should receive only the event with seq=2
            data = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
            assert data["seq"] == 2
            assert data["payload"]["i"] == 2

    repo.clear()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_ws_handler.py::test_ws_since_seq_param -v`
Expected: FAIL — endpoint doesn't read `since_seq` param yet.

**Step 3: Modify ws_handler.py**

Change `websocket_endpoint` in `server/ws_handler.py:250-307`:

```python
@router.websocket("/workflows/{workflow_id}")
async def websocket_endpoint(
    workflow_id: str,
    websocket: WebSocket,
    user_id: str | None = Query(None),
    since_seq: int | None = Query(None),
):
    """WebSocket endpoint for real-time workflow events.

    Args:
        since_seq: If provided, only replay events with seq > since_seq.
                   Pass 0 for full replay, or the last seen seq for reconnect.
    """
    manager = get_connection_manager()

    from server.repository import get_repository
    repo = get_repository()
    data = repo.get(workflow_id)
    event_bus = data.get("event_bus") if data else None
    if not event_bus:
        from server.routes import _new_bus
        event_bus = _new_bus()

    # Pass since_seq to subscribe for cursor-based replay
    sub_id = await manager.connect(
        workflow_id, websocket, event_bus,
        user_id=user_id, filter_by_user=False,
        since_seq=since_seq,
    )

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "chat.answer":
                question_id = message.get("payload", {}).get("question_id")
                answer = message.get("payload", {}).get("answer")
                if question_id and answer:
                    from harness.tools.ask_human import resolve_question
                    await resolve_question(question_id, answer)

            elif message.get("type") == "agent.stop_and_regenerate":
                payload = message.get("payload", {}) or {}
                agent_name = payload.get("agent_name") or ""
                partial_output = payload.get("partial_output") or ""
                user_guidance = payload.get("user_guidance") or ""
                if agent_name:
                    from harness.engine.macro_graph import request_stop_and_regenerate
                    await request_stop_and_regenerate(
                        workflow_id, agent_name, partial_output, user_guidance,
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(sub_id, event_bus)
```

Now update `ConnectionManager.connect` in `server/ws_handler.py:68-127` to accept and pass `since_seq`:

```python
async def connect(
    self,
    workflow_id: str,
    websocket: WebSocket,
    event_bus: EventBus,
    user_id: str | None = None,
    filter_by_user: bool = True,
    since_seq: int | None = None,
) -> str:
    """Accept a WebSocket connection and subscribe to EventBus.

    Args:
        since_seq: Pass to Bus.subscribe for cursor-based replay.
    """
    await websocket.accept()

    ws_user_id = user_id
    if not ws_user_id:
        ws_user_id = websocket.query_params.get("user_id")
    if not ws_user_id:
        api_key = websocket.headers.get("x-api-key", websocket.headers.get("X-API-Key"))
        ws_user_id = self._resolve_user_id(api_key)
    if not ws_user_id:
        import uuid
        ws_user_id = f"anon-{uuid.uuid4().hex[:8]}"

    # Subscribe with cursor
    sub_id, queue = await event_bus.subscribe(since_seq=since_seq)

    if self._lock is None:
        from asyncio import Lock
        self._lock = Lock()

    async with self._lock:
        self._connections[sub_id] = websocket
        self._sub_to_user[sub_id] = ws_user_id
        if ws_user_id not in self._user_connections:
            self._user_connections[ws_user_id] = []
        self._user_connections[ws_user_id].append(sub_id)

    task = asyncio.create_task(
        self._forward_events_filtered(
            sub_id, queue, websocket, ws_user_id,
            filter_by_user=filter_by_user,
        )
    )
    async with self._lock:
        self._tasks[sub_id] = task

    return sub_id
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_ws_handler.py -v`
Expected: PASS

**Step 5: Run full server test suite**

Run: `pytest tests/server/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add server/ws_handler.py tests/server/test_ws_handler.py
git commit -m "feat: WS endpoint accepts since_seq query param for cursor-based replay"
```

---

### Task 3: Completed-run read-only Bus from persisted events

**Files:**
- Modify: `server/routes.py:563-621`
- Modify: `server/ws_handler.py:258-270`

**Why:** When a workflow completes, `runner.py:413` removes the Bus from the repository. Currently `ws_handler.py:269` creates an empty Bus, so completed runs return zero events via WS. We need to reconstruct a Bus from the persisted `events` array so that WS replay works for completed runs too.

**Step 1: Write the failing test**

Add to `tests/server/test_ws_handler.py`:

```python
@pytest.mark.asyncio
async def test_ws_completed_run_replays_persisted_events():
    """Connecting to a completed workflow's WS replays events from disk."""
    from harness.run_store import RunStore

    run_id = "completed-replay-test"
    events = [
        {"type": "workflow.started", "ts": 1.0, "seq": 1, "payload": {"workflow_id": run_id}},
        {"type": "node.started", "ts": 2.0, "seq": 2, "payload": {"workflow_id": run_id, "node_id": "n1", "agent_name": "agent1"}},
    ]

    RunStore().save(
        run_id=run_id,
        workflow_name="test-wf",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        events=events,
    )

    # No in-memory entry — simulates completed workflow
    repo = get_repository()
    # Don't put anything in repo — Bus was already removed

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.websocket_connect(f"/ws/workflows/{run_id}?user_id=test&since_seq=0") as ws:
            received = []
            try:
                while True:
                    data = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    received.append(data)
            except asyncio.TimeoutError:
                pass

            assert len(received) >= 2
            assert received[0]["type"] == "workflow.started"
            assert received[1]["type"] == "node.started"

    # Cleanup
    import os
    os.remove(os.path.join(str(RunStore()._dir), f"{run_id}.json"))
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_ws_handler.py::test_ws_completed_run_replays_persisted_events -v`
Expected: FAIL — completed runs get an empty Bus, so zero events are replayed.

**Step 3: Add `_rebuild_bus_from_events` helper to ws_handler.py**

Add before `websocket_endpoint` in `server/ws_handler.py`:

```python
def _rebuild_bus_from_events(workflow_id: str) -> "Bus | None":
    """Reconstruct a read-only Bus from persisted events for completed runs.

    Returns None if no events file exists or events list is empty.
    """
    from harness.run_store import RunStore
    run = RunStore().get_run(workflow_id)
    if not run or not run.get("events"):
        return None

    from harness.extensions.bus import Bus
    bus = Bus()
    events = run["events"]
    # Re-inject events into buffer and set seq counter
    max_seq = 0
    for event in events:
        seq = event.get("seq", 0)
        if seq > max_seq:
            max_seq = seq
        bus._buffer.append(event)
    bus._seq = max_seq
    return bus
```

**Step 4: Modify ws_handler.py websocket_endpoint to use rebuilt Bus**

Change the Bus resolution block in `websocket_endpoint`:

```python
@router.websocket("/workflows/{workflow_id}")
async def websocket_endpoint(
    workflow_id: str,
    websocket: WebSocket,
    user_id: str | None = Query(None),
    since_seq: int | None = Query(None),
):
    manager = get_connection_manager()

    from server.repository import get_repository
    repo = get_repository()
    data = repo.get(workflow_id)
    event_bus = data.get("event_bus") if data else None

    if not event_bus:
        # Workflow completed — Bus was GC'd. Try rebuilding from persisted events.
        event_bus = _rebuild_bus_from_events(workflow_id)
        if not event_bus:
            # No persisted events either — empty Bus for bidirectional messages only.
            from server.routes import _new_bus
            event_bus = _new_bus()

    sub_id = await manager.connect(
        workflow_id, websocket, event_bus,
        user_id=user_id, filter_by_user=False,
        since_seq=since_seq,
    )

    # ... rest unchanged (try/finally block with chat.answer + stop_and_regenerate)
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/server/test_ws_handler.py -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `pytest tests/server/ -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add server/ws_handler.py tests/server/test_ws_handler.py
git commit -m "feat: completed runs rebuild read-only Bus from persisted events for WS replay"
```

---

### Task 4: Ensure all persisted events have `seq` field

**Files:**
- Modify: `harness/extensions/collectors.py` (if it strips seq)
- Modify: `server/runner.py:285-290` (where events are persisted)

**Why:** When `runner.py` persists `events = list(event_bus.buffer)` on completion, the events must include the `seq` field so that `_rebuild_bus_from_events` can restore it. Also need to verify the runner's `saveConversation` collector doesn't depend on missing seq.

**Step 1: Verify events are persisted with seq**

Run: `grep -n "event_bus.buffer\|list(event_bus" server/runner.py`

Check that `events = list(event_bus.buffer)` is used (it is, at lines 289 and 361). Since Task 1 added `seq` to every emitted event, `event_bus.buffer` already contains events with `seq`. No code change needed in runner.py.

**Step 2: Check that ConversationCollector doesn't strip seq**

Read: `harness/extensions/collectors.py` — verify it only extracts conversation messages from buffer, doesn't modify events.

**Step 3: Verify with a quick integration check**

Run: `pytest tests/harness/extensions/ -v`
Expected: ALL PASS

**Step 4: Commit (if any changes needed)**

Only commit if actual changes were required. If events already flow through with seq, no commit needed.

---

### Task 5: Frontend — Reset scoped stores on workflow switch + pass since_seq to WS

**Files:**
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx:64-157`
- Modify: `frontend/src/hooks/useWebSocket.ts:56-75`
- Modify: `frontend/src/contexts/workflow-context/useWorkflowWS.ts`

**Why:** This is the core fix. When `workflowId` changes, scoped stores must be reset before the WS reconnects. The WS must connect with `since_seq=0` for a full replay from the server.

**Step 1: Add `since_seq` support to `useWebSocket`**

Modify `frontend/src/hooks/useWebSocket.ts`:

Add `sinceSeq` to the options interface:

```typescript
export interface UseWebSocketOptions {
  workflowId: string | null;
  onEvent?: (event: WSEvent) => void;
  autoReconnect?: boolean;
  reconnectDelay?: number;
  sinceSeq?: number;  // cursor for replay; 0 = full replay, undefined = no replay
}
```

In the `connect` callback, add `since_seq` to the URL:

```typescript
const connect = useCallback(() => {
  if (!workflowId) return;
  disconnect();
  cancelledRef.current = false;

  let userId = getUserId();
  const apiKey = getApiKey();
  if (!userId && apiKey) {
    userId = getUserFromApiKey(apiKey);
  }
  if (!userId) {
    userId = "default";
  }

  const base = getWsBaseUrl();
  let url = `${base}/ws/workflows/${workflowId}?user_id=${userId}`;
  if (sinceSeq !== undefined) {
    url += `&since_seq=${sinceSeq}`;
  }
  const ws = new WebSocket(url);

  // ... rest unchanged
}, [workflowId, autoReconnect, reconnectDelay, disconnect, sinceSeq]);
```

**Step 2: Modify WorkflowScope to reset stores and use since_seq=0**

Replace `WorkflowScope.tsx`:

```typescript
"use client";

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";
import { replayEventsToStores, loadLegacyRunData } from "./replayEvents";
import { fetchWithAuth } from "@/lib/api";

// ============================================================
// WSMethodContext — React context for WebSocket send methods
// ============================================================

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

// ============================================================
// WorkflowScope
// ============================================================

interface WorkflowScopeProps {
  workflowId: string | null;
  children: ReactNode;
}

function resetAllStores(stores: import("./workflowStores").WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
  stores.span.getState().reset();
}

export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);
  const prevWorkflowIdRef = useRef<string | null>(null);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    // Reset scoped stores when switching to a DIFFERENT workflow
    if (workflowId && workflowId !== prevWorkflowIdRef.current) {
      const entry = manager.getOrCreate(workflowId);
      resetAllStores(entry.stores);
    }
    prevWorkflowIdRef.current = workflowId;
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  if (!stores) return <>{children}</>;

  return (
    <WorkflowProvider
      workflowId={workflowId}
      stores={stores}
      setActiveWorkflowId={setActiveWorkflowId}
    >
      {children}
    </WorkflowProvider>
  );
}
```

Key changes:
- Added `resetAllStores()` call when `workflowId` changes
- Removed the 5-second REST fallback timer (no longer needed — WS replay is the single path)
- Removed the `replayEventsToStores` / `loadLegacyRunData` calls from WorkflowScope (WS handles this now)

**Step 3: Pass since_seq=0 from useWorkflowWS**

Modify `frontend/src/contexts/workflow-context/useWorkflowWS.ts`:

```typescript
export function useWorkflowWS(workflowId: string | null): WorkflowWSReturn {
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchMode = activeBatchId !== null;

  const onEvent = useCallback((event: WSEvent) => {
    if (batchMode) {
      dispatchBatchEvent(event);
    } else {
      dispatchSingleEvent(event, workflowId);
    }
  }, [batchMode, workflowId]);

  const singleWs = useWebSocket({
    workflowId: batchMode ? null : workflowId,
    onEvent,
    sinceSeq: 0,  // Always request full replay from server on connect
  });

  // ... rest unchanged
```

**Step 4: Build and check for TypeScript errors**

Run: `cd frontend && npm run build`
Expected: Clean build with no errors.

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/WorkflowScope.tsx frontend/src/hooks/useWebSocket.ts frontend/src/contexts/workflow-context/useWorkflowWS.ts
git commit -m "feat: reset scoped stores on switch + WS connects with since_seq=0 for full replay"
```

---

### Task 6: Fix RunHistoryList — running workflow click uses scoped path

**Files:**
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx:95-108`

**Why:** Currently `handleClickRun` for running workflows calls the legacy `setActiveWorkflowId` which only operates on global stores. It should use the viewStore + WorkflowManager path instead, consistent with completed runs.

**Step 1: Modify handleClickRun**

Change `RunHistoryList.tsx`:

```typescript
const handleClickRun = async (run: RunRecord) => {
  onLeaveBenchmark?.();
  selectRun(run.run_id);
  if (run.status === "running") {
    // Switch to live view — WorkflowScope handles scoped store reset + WS replay
    setWorkflow(run.run_id, run.workflow_name, null);
    showLive();
    return;
  }
  const full = await fetchRun(run.run_id);
  if (full) showReplay(full);
};
```

Remove the `setActiveWorkflowId` import (line 9) since it's no longer used here.

**Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: Clean build.

**Step 3: Commit**

```bash
git add frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "fix: running workflow click uses WorkflowManager path instead of legacy setActiveWorkflowId"
```

---

### Task 7: Fix `loadLegacyRunData` — reset ALL 8 stores, not just 3

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts:382-385`

**Why:** `loadLegacyRunData` only resets conversation/chart/workflow stores, leaving toolCall/agentIO/chat/span with stale data. This causes dirty state to leak between workflow views.

**Step 1: Change reset to use the shared `resetAllStores` function**

In `replayEvents.ts`, the `resetAllStores` function already exists (lines 81-90). But `loadLegacyRunData` at line 383-385 only calls reset on 3 stores. Fix:

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

  // Reset ALL stores (not just conversation/chart/workflow)
  resetAllStores(stores);

  // ... rest of the function unchanged
```

**Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: Clean build.

**Step 3: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts
git commit -m "fix: loadLegacyRunData resets all 8 scoped stores, not just 3"
```

---

### Task 8: Simplify viewStore.showReplay — remove redundant safety net

**Files:**
- Modify: `frontend/src/stores/viewStore.ts`

**Why:** With WS replay as the single authoritative path and `resetAllStores` always called on switch, the "safety net" in `showReplay` (lines 50-78) is no longer needed. For completed runs, WS reconnect will replay all events. For the `showReplay` code path (user clicks completed run in history), the existing `replayEventsToStores` + `loadLegacyRunData` both call `resetAllStores`, so the safety net is dead code.

**Step 1: Simplify showReplay**

```typescript
import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData } from "@/contexts/workflow-context/replayEvents";

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

    // Ensure scoped stores exist for this workflow
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);

    // Replay events into scoped stores (both paths call resetAllStores internally)
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

    set({ activeView: { type: "replay", runId: run.run_id, run } });
  },
}));
```

**Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: Clean build.

**Step 3: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "refactor: remove redundant safety net from showReplay — resetAllStores handles it"
```

---

### Task 9: Frontend build + full integration test

**Files:**
- No new files — verification only

**Step 1: Build frontend**

Run: `cd frontend && npm run build`
Fix any TypeScript compilation errors.

**Step 2: Run full backend test suite**

Run: `pytest tests/ -v --ignore=tests/engine`
Expected: ALL PASS

**Step 3: Manual integration test**

Run: `bash examples/launch_ui.sh`

Test matrix:
1. Start a workflow → watch it complete live → all tabs populated (conversation, results, analysis, diagnostics)
2. Click the same completed run in history → all tabs should show identical data (WS replay from rebuilt Bus)
3. Start a workflow → switch away to a completed run → switch back → no conversation stacking
4. Click an old run (no events field) → should still show conversation, charts, DAG via loadLegacyRunData
5. Click a running workflow in history → should switch to live view with WS replay from cursor
6. Start a run → let it complete → immediately click the same run → should show full data (no "completed but empty" bug)

**Step 4: Commit build artifacts**

```bash
git add frontend/out/
git commit -m "build: frontend rebuild after WS seq cursor implementation"
```

---

### Task 10: Push and verify

**Step 1: Push to main**

```bash
git push origin main
```

**Step 2: Verify on deployed instance**

Repeat the test matrix from Task 9.

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Bus.seq + since_seq | Backward compat — subscribe() without since_seq still replays all | Default param = None preserves old behavior |
| WS since_seq param | Old clients that don't send since_seq get full replay (backward compat) | Default Query(None) |
| Completed-run Bus rebuild | Memory: large event arrays reloaded into Bus buffer | Bus has buffer_size cap (2000); completed runs are read-only and short-lived (GC after WS closes) |
| WorkflowScope resetAllStores | Flash of empty UI before WS replay fills stores | Acceptable — same as initial page load experience |
| Removing REST fallback | If WS fails entirely, no data shows | WS auto-reconnects with backoff; worst case user refreshes |
| Removing legacy setActiveWorkflowId call from RunHistoryList | Other callers still use it (WorkflowLauncher, userStore, etc.) | Only removed from RunHistoryList; legacy function kept for other callers |

---

## What This Fixes

| Bug | Fixed by |
|-----|---------|
| Conversation stacking on switch | Task 5 (resetAllStores) + Task 5 (since_seq=0 = no double-replay) |
| Completed run shows empty | Task 3 (rebuild Bus from persisted events) + Task 5 (since_seq=0 replay) |
| loadLegacyRunData partial reset | Task 7 (reset all 8 stores) |
| Legacy setActiveWorkflowId for running clicks | Task 6 (use WorkflowManager path) |
| REST fallback race conditions | Task 5 (removed — WS replay is single path) |
| Redundant safety net code | Task 8 (removed dead code) |
