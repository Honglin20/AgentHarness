# Backend-Owned Data Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move conversation and chart_groups persistence from frontend (fire-and-forget PATCH) to backend (collected during execution, saved atomically with the run record).

**Architecture:** Add two collectors to the Bus/extension system that subscribe to events during workflow execution: (1) a ConversationCollector that builds conversation messages from node lifecycle, text_delta, and tool events, and (2) a ChartCollector that accumulates chart.render side-effects. Both are written to RunStore.save() alongside existing agent_io and result data. Frontend PATCH endpoints are kept as fallbacks but are no longer the primary persistence path.

**Tech Stack:** Python (backend), existing Bus extension system, RunStore JSON persistence

---

## Design Principle

**Single Source of Truth**: The backend owns all persisted data. The frontend is a display layer. Data that flows through WebSocket events should be collected by the backend during execution, not re-constructed by the frontend and PATCHed back.

**Why this approach over fixing the frontend race condition**: The current architecture has the frontend responsible for persistence — a violation of separation of concerns. Fixing the race condition (await, snapshots, etc.) would be a band-aid. Moving persistence to the backend eliminates the entire class of race conditions.

---

### Task 1: Add chart_groups collection to RunStore.save()

**Files:**
- Modify: `harness/run_store.py:28-60`
- Modify: `server/runner.py:268-280,316-328`
- Test: `tests/test_run_store.py`

**Step 1: Write the failing test**

Add to `tests/test_run_store.py`:

```python
def test_save_and_retrieve_chart_groups():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        chart_groups = {
            "groups": {
                "Run Summary": {
                    "label": "Run Summary",
                    "collapsed": False,
                    "charts": {
                        "Tokens": {
                            "title": "Tokens",
                            "chart_type": "bar",
                            "data": [{"agent": "a1", "tokens": 100}],
                            "columns": ["agent", "tokens"],
                            "x": "agent",
                            "y": "tokens",
                        }
                    },
                    "table": None,
                }
            },
            "groupOrder": ["Run Summary"],
        }
        store.save(
            run_id="run-charts",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            chart_groups=chart_groups,
        )
        run = store.get_run("run-charts")
        assert run["chart_groups"]["groupOrder"] == ["Run Summary"]
        assert "Tokens" in run["chart_groups"]["groups"]["Run Summary"]["charts"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py::test_save_and_retrieve_chart_groups -v`
Expected: FAIL — `save() got an unexpected keyword argument 'chart_groups'`

**Step 3: Add chart_groups parameter to RunStore.save()**

In `harness/run_store.py`, update the `save` method signature to include `chart_groups: dict | None = None`, and add to the record:

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
) -> Path:
    record = {
        "run_id": run_id,
        "workflow_name": workflow_name,
        "agents_snapshot": agents_snapshot,
        "status": status,
        "inputs": inputs,
        "result": result,
        "dag": dag,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if agent_io:
        record["agent_io"] = agent_io
    if batch_id:
        record["batch_id"] = batch_id
    if user_id:
        record["user_id"] = user_id
    if chart_groups:
        record["chart_groups"] = chart_groups
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/run_store.py tests/test_run_store.py
git commit -m "feat: add chart_groups parameter to RunStore.save()"
```

---

### Task 2: Add ConversationCollector to Bus extension system

**Files:**
- Create: `harness/extensions/collectors.py`
- Test: `tests/harness/extensions/test_collectors.py`

This collector subscribes to Bus events during workflow execution and builds a conversation array (same structure the frontend currently builds from events).

**Step 1: Write the failing test**

Create `tests/harness/extensions/test_collectors.py`:

```python
import pytest
from harness.extensions.bus import Bus
from harness.extensions.collectors import ConversationCollector


def test_conversation_collector_agent_text():
    bus = Bus()
    collector = ConversationCollector(bus)

    # Simulate agent text delta events
    bus.emit("node.started", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "text": "Hello "})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "text": "world"})
    bus.emit("node.completed", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "duration_ms": 100})

    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "Hello world"
    assert messages[0]["agentName"] == "agent1"
    assert messages[0]["status"] == "done"


def test_conversation_collector_tool_call():
    bus = Bus()
    collector = ConversationCollector(bus)

    bus.emit("node.started", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "text": "Running bash"})
    bus.emit("trace.tool_call", {
        "workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1",
        "tool_name": "bash", "tool_args": {"command": "ls"},
    })
    bus.emit("trace.tool_result", {
        "workflow_id": "w1", "node_id": "agent1", "tool_name": "bash",
        "tool_result": "file1.txt\nfile2.txt",
    })
    bus.emit("node.completed", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "duration_ms": 200})

    messages = collector.get_messages()
    assert len(messages) == 2
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "Running bash"
    assert messages[1]["type"] == "tool_call"
    assert messages[1]["toolName"] == "bash"
    assert messages[1]["toolResult"] == "file1.txt\nfile2.txt"


def test_conversation_collector_node_failed():
    bus = Bus()
    collector = ConversationCollector(bus)

    bus.emit("node.started", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1"})
    bus.emit("agent.text_delta", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "text": "Oops"})
    bus.emit("node.failed", {"workflow_id": "w1", "node_id": "agent1", "agent_name": "agent1", "error": "timeout", "duration_ms": 5000})

    messages = collector.get_messages()
    assert len(messages) == 1
    assert messages[0]["status"] == "error"
    assert messages[0]["content"] == "Oops\n\n**Error:** timeout"


def test_conversation_collector_chat():
    bus = Bus()
    collector = ConversationCollector(bus)

    bus.emit("chat.question", {
        "workflow_id": "w1", "question_id": "q1",
        "question": "What should I do?", "agent_name": "agent1",
    })
    bus.emit("chat.answer", {
        "workflow_id": "w1", "question_id": "q1", "answer": "Continue",
    })

    messages = collector.get_messages()
    assert len(messages) == 2
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "What should I do?"
    assert messages[1]["type"] == "user"
    assert messages[1]["content"] == "Continue"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/extensions/test_collectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.extensions.collectors'`

**Step 3: Implement ConversationCollector**

Create `harness/extensions/collectors.py`:

```python
"""Collectors that subscribe to Bus events during workflow execution.

ConversationCollector builds a conversation array from node lifecycle,
text_delta, tool, and chat events — the same structure the frontend
builds from WebSocket events.
"""
from __future__ import annotations

from harness.extensions.bus import Bus


class ConversationCollector:
    """Collects Bus events into a conversation message array.

    Subscribes to the Bus buffer during workflow execution and builds
    messages that match the frontend's ConversationMessage structure,
    so replay works identically whether conversation was saved by
    backend or frontend.
    """

    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._messages: list[dict] = []
        self._counter = 0
        self._streaming_node: dict | None = None
        self._pending_tool_calls: dict[str, dict] = {}  # node_id+tool_name -> msg

    def _next_id(self) -> str:
        self._counter += 1
        return f"msg-{self._counter}"

    def collect_from_buffer(self) -> None:
        """Process all buffered events and build conversation messages."""
        for event in self._bus.buffer:
            self._process_event(event)

    def _process_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        payload = event.get("payload", {})

        if event_type == "agent.text_delta":
            self._handle_text_delta(payload)
        elif event_type == "node.completed":
            self._handle_node_completed(payload)
        elif event_type == "node.failed":
            self._handle_node_failed(payload)
        elif event_type == "trace.tool_call":
            self._handle_tool_call(payload)
        elif event_type == "trace.tool_result":
            self._handle_tool_result(payload)
        elif event_type == "chat.question":
            self._handle_chat_question(payload)
        elif event_type == "chat.answer":
            self._handle_chat_answer(payload)

    def _handle_text_delta(self, payload: dict) -> None:
        node_id = payload.get("node_id", "")
        text = payload.get("text", "")
        agent_name = payload.get("agent_name", "")

        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["content"] += text
        else:
            # Finalize previous streaming node if different
            if self._streaming_node:
                self._streaming_node["status"] = "done"
                self._messages.append(self._streaming_node)
            self._streaming_node = {
                "id": self._next_id(),
                "type": "agent",
                "nodeId": node_id,
                "agentName": agent_name,
                "content": text,
                "status": "streaming",
                "timestamp": payload.get("ts", 0),
            }

    def _finalize_streaming(self, node_id: str) -> None:
        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._messages.append(self._streaming_node)
            self._streaming_node = None

    def _handle_node_completed(self, payload: dict) -> None:
        node_id = payload.get("node_id", "")
        agent_name = payload.get("agent_name", "")
        duration_ms = payload.get("duration_ms")

        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "done"
            self._streaming_node["agentName"] = agent_name
            if duration_ms is not None:
                self._streaming_node["durationMs"] = duration_ms
            self._messages.append(self._streaming_node)
            self._streaming_node = None

    def _handle_node_failed(self, payload: dict) -> None:
        node_id = payload.get("node_id", "")
        agent_name = payload.get("agent_name", "")
        error = payload.get("error", "")
        duration_ms = payload.get("duration_ms")

        if self._streaming_node and self._streaming_node.get("nodeId") == node_id:
            self._streaming_node["status"] = "error"
            self._streaming_node["agentName"] = agent_name
            self._streaming_node["content"] += f"\n\n**Error:** {error}"
            if duration_ms is not None:
                self._streaming_node["durationMs"] = duration_ms
            self._messages.append(self._streaming_node)
            self._streaming_node = None

    def _handle_tool_call(self, payload: dict) -> None:
        node_id = payload.get("node_id", "")
        agent_name = payload.get("agent_name", "")
        tool_name = payload.get("tool_name", "")
        tool_args = payload.get("tool_args", {})

        # Finalize any streaming text before the tool call
        self._finalize_streaming(node_id)

        key = f"{node_id}:{tool_name}"
        msg = {
            "id": self._next_id(),
            "type": "tool_call",
            "nodeId": node_id,
            "agentName": agent_name,
            "content": "",
            "toolName": tool_name,
            "toolArgs": tool_args,
            "toolStatus": "running",
            "timestamp": payload.get("ts", 0),
        }
        self._pending_tool_calls[key] = msg
        self._messages.append(msg)

    def _handle_tool_result(self, payload: dict) -> None:
        node_id = payload.get("node_id", "")
        tool_name = payload.get("tool_name", "")
        result = payload.get("tool_result", "")

        key = f"{node_id}:{tool_name}"
        msg = self._pending_tool_calls.pop(key, None)
        if msg:
            elapsed = (payload.get("ts", 0) - msg["timestamp"]) if msg.get("timestamp") else None
            msg["toolResult"] = result
            msg["toolStatus"] = "done"
            if elapsed is not None:
                msg["toolDurationMs"] = elapsed

    def _handle_chat_question(self, payload: dict) -> None:
        self._finalize_streaming("")
        self._messages.append({
            "id": self._next_id(),
            "type": "agent",
            "content": payload.get("question", ""),
            "agentName": payload.get("agent_name", ""),
            "status": "done",
            "timestamp": payload.get("ts", 0),
        })

    def _handle_chat_answer(self, payload: dict) -> None:
        self._messages.append({
            "id": self._next_id(),
            "type": "user",
            "content": payload.get("answer", ""),
            "timestamp": payload.get("ts", 0),
        })

    def get_messages(self) -> list[dict]:
        """Return collected conversation messages."""
        result = list(self._messages)
        if self._streaming_node:
            self._streaming_node["status"] = "done"
            result.append(self._streaming_node)
        return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/extensions/collectors.py tests/harness/extensions/test_collectors.py
git commit -m "feat: add ConversationCollector for backend-owned conversation persistence"
```

---

### Task 3: Wire ConversationCollector into runner._run_workflow

**Files:**
- Modify: `server/runner.py:230-340`

**Step 1: Understand the integration point**

The runner's `_run_workflow()` method executes the workflow and then persists results via `RunStore().save()`. The `event_bus` (Bus instance) already has a `buffer` that contains all events emitted during execution.

After the workflow completes (success or failure), we:
1. Create a `ConversationCollector`
2. Call `collector.collect_from_buffer()` to process all buffered events
3. Pass `conversation=collector.get_messages()` to `RunStore().save()`

**Step 2: Add conversation parameter to RunStore.save()**

In `harness/run_store.py`, add `conversation: list[dict] | None = None` parameter:

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
) -> Path:
```

And in the record building:
```python
    if conversation:
        record["conversation"] = conversation
```

**Step 3: Wire into runner success path**

In `server/runner.py`, after the successful `RunStore().save()` call (around line 268), add conversation collection:

```python
                # Collect conversation from event buffer
                conversation = None
                try:
                    from harness.extensions.collectors import ConversationCollector
                    conv_collector = ConversationCollector(event_bus)
                    conv_collector.collect_from_buffer()
                    conversation = conv_collector.get_messages()
                except Exception:
                    pass

                RunStore().save(
                    run_id=workflow_id,
                    workflow_name=workflow.name,
                    agents_snapshot=...,
                    status="completed",
                    inputs=inputs,
                    result=...,
                    dag=...,
                    agent_io=_agent_io,
                    batch_id=batch_id,
                    user_id=user_id,
                    conversation=conversation,
                )
```

**Step 4: Wire into runner failure path**

Same pattern in the failure path (around line 316):

```python
                # Collect conversation from event buffer
                conversation = None
                try:
                    from harness.extensions.collectors import ConversationCollector
                    conv_collector = ConversationCollector(event_bus)
                    conv_collector.collect_from_buffer()
                    conversation = conv_collector.get_messages()
                except Exception:
                    pass

                RunStore().save(
                    ...,
                    conversation=conversation,
                )
```

**Step 5: Run tests**

Run: `pytest tests/test_run_store.py tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/run_store.py server/runner.py
git commit -m "feat: wire ConversationCollector into runner for backend-owned persistence"
```

---

### Task 4: Add ChartCollector and wire into runner

**Files:**
- Modify: `harness/extensions/collectors.py`
- Modify: `server/runner.py`
- Test: `tests/harness/extensions/test_collectors.py`

**Step 1: Write the failing test**

Add to `tests/harness/extensions/test_collectors.py`:

```python
from harness.extensions.collectors import ChartCollector


def test_chart_collector():
    bus = Bus()
    collector = ChartCollector(bus)

    # Simulate chart.render events from plugins
    bus.emit("chart.render", {
        "node_id": "agent1",
        "chart_type": "bar",
        "data": [{"agent": "a1", "tokens": 100}],
        "columns": ["agent", "tokens"],
        "x": "agent",
        "y": "tokens",
        "label": "Run Summary",
        "title": "Token Usage",
        "category": "analysis",
    })
    bus.emit("chart.render", {
        "node_id": "agent1",
        "chart_type": "table",
        "data": [{"agent": "a1", "status": "success"}],
        "columns": ["agent", "status"],
        "label": "Run Summary",
        "title": "Summary Table",
    })

    chart_groups = collector.get_chart_groups()
    assert "Run Summary" in chart_groups["groups"]
    assert chart_groups["groupOrder"] == ["Run Summary"]
    group = chart_groups["groups"]["Run Summary"]
    assert "Token Usage" in group["charts"]
    assert group["table"] is not None
    assert group["table"]["rows"][0]["agent"] == "a1"


def test_chart_collector_multiple_groups():
    bus = Bus()
    collector = ChartCollector(bus)

    bus.emit("chart.render", {
        "chart_type": "bar", "data": [], "columns": [],
        "x": "x", "y": "y", "label": "Group A", "title": "Chart 1",
    })
    bus.emit("chart.render", {
        "chart_type": "line", "data": [], "columns": [],
        "x": "x", "y": "y", "label": "Group B", "title": "Chart 2",
    })

    chart_groups = collector.get_chart_groups()
    assert chart_groups["groupOrder"] == ["Group A", "Group B"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/extensions/test_collectors.py::test_chart_collector -v`
Expected: FAIL — `ImportError: cannot import name 'ChartCollector'`

**Step 3: Implement ChartCollector**

Add to `harness/extensions/collectors.py`:

```python
class ChartCollector:
    """Collects chart.render events from Bus buffer into chart_groups structure.

    Builds the same structure as the frontend's chartStore, so replay
    works identically.
    """

    def __init__(self, bus: Bus) -> None:
        self._bus = bus

    def collect_from_buffer(self) -> None:
        """Process buffered events — called automatically by get_chart_groups()."""
        pass  # Processing happens in get_chart_groups for simplicity

    def get_chart_groups(self) -> dict:
        """Return chart_groups structure from buffered chart.render events."""
        groups: dict[str, dict] = {}
        group_order: list[str] = []

        for event in self._bus.buffer:
            if event.get("type") != "chart.render":
                continue
            payload = event.get("payload", {})

            label = payload.get("label", "Default")
            title = payload.get("title", "Untitled")
            chart_type = payload.get("chart_type", "bar")
            category = payload.get("category")

            if label not in groups:
                groups[label] = {
                    "label": label,
                    "collapsed": False,
                    "category": category,
                    "charts": {},
                    "table": None,
                }
                group_order.append(label)

            group = groups[label]
            if chart_type == "table":
                group["table"] = {
                    "columns": payload.get("columns", []),
                    "rows": payload.get("data", []),
                }
            else:
                group["charts"][title] = {
                    "label": label,
                    "title": title,
                    "chart_type": chart_type,
                    "data": payload.get("data", []),
                    "columns": payload.get("columns", []),
                    "x": payload.get("x"),
                    "y": payload.get("y"),
                    "hue": payload.get("hue"),
                    "category": category,
                }

        return {"groups": groups, "groupOrder": group_order}
```

**Step 4: Wire into runner**

In `server/runner.py`, alongside the ConversationCollector, add ChartCollector in both success and failure paths:

```python
                # Collect charts from event buffer
                chart_groups = None
                try:
                    from harness.extensions.collectors import ChartCollector
                    chart_collector = ChartCollector(event_bus)
                    chart_groups = chart_collector.get_chart_groups()
                    if not chart_groups.get("groupOrder"):
                        chart_groups = None
                except Exception:
                    pass
```

Then pass `chart_groups=chart_groups` to `RunStore().save()`.

**Step 5: Run tests**

Run: `pytest tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/extensions/collectors.py server/runner.py tests/harness/extensions/test_collectors.py
git commit -m "feat: add ChartCollector and wire into runner for backend-owned chart persistence"
```

---

### Task 5: Ensure tool events are emitted for collection

**Files:**
- Modify: `harness/engine/macro_graph.py` (if needed)

**Step 1: Audit which events the ConversationCollector depends on**

The collector needs these events to build conversation:
- `agent.text_delta` — already emitted by macro_graph.py
- `node.started` / `node.completed` / `node.failed` — already emitted
- `trace.tool_call` / `trace.tool_result` — need to verify these exist
- `chat.question` / `chat.answer` — already emitted

**Step 2: Check if trace.tool_call and trace.tool_result exist**

Search macro_graph.py for `trace.tool_call` emission. If they don't exist, they need to be added where tool calls are made (in the Pydantic AI agent execution loop).

**Step 3: Add missing tool events if needed**

If `trace.tool_call` and `trace.tool_result` don't exist, add them at the point where tools are invoked within macro_graph.py's agent node execution. The tool name and args are available before execution, and the result is available after.

**Step 4: Run all tests**

Run: `pytest tests/ -v --ignore=tests/harness/engine/ -m "not slow"`
Expected: ALL PASS

**Step 5: Commit (if changes were needed)**

```bash
git add harness/engine/macro_graph.py
git commit -m "feat: emit trace.tool_call/tool_result events for backend conversation collection"
```

---

### Task 6: Remove frontend PATCH as primary persistence path

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:92-113,161-186`

**Step 1: Make _saveConversation and _saveCharts defensive**

Instead of removing them entirely (they serve as fallback for in-progress runs), make them defensive:

In `useWorkflowEvents.ts`, change `_saveConversation` to skip if conversation is empty (preventing the race condition overwrite):

```typescript
function _saveConversation(workflowId: string | undefined): void {
  if (!workflowId) return;
  const messages = useConversationStore.getState().messages;
  if (messages.length === 0) return; // Don't overwrite backend data with empty
  fetchWithAuth(`/api/runs/${workflowId}/conversation`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation: messages }),
  }).catch(() => {});
}
```

Same for `_saveCharts`:
```typescript
function _saveCharts(workflowId: string | undefined): void {
  if (!workflowId) return;
  const { groups, groupOrder } = useChartStore.getState();
  if (groupOrder.length === 0) return; // Don't overwrite backend data with empty
  fetchWithAuth(`/api/runs/${workflowId}/charts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chart_groups: { groups, groupOrder } }),
  }).catch(() => {});
}
```

**Step 2: Verify frontend still works for live runs and replay**

The frontend PATCH still fires (as backup), but the backend now has the primary copy. Replay loads from `fetchRun()` which returns backend-persisted data.

**Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "fix: make frontend PATCH defensive — skip empty saves to prevent overwriting backend data"
```

---

### Task 7: End-to-end verification

**Files:**
- No code changes

**Step 1: Start the backend**

Run: `python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`

**Step 2: Start the frontend**

Run: `cd frontend && npm run build && cd ..`

**Step 3: Verify in browser**

1. Select a user (e.g., testuser)
2. Start a workflow run
3. Wait for it to complete
4. Check the run record directly: `cat runs/{run_id}.json | python3 -m json.tool | grep -A5 conversation`
5. Verify conversation has messages
6. Verify chart_groups has data
7. Click another run in sidebar, then click back — conversation should still be visible
8. Switch users — runs should be isolated
9. Switch back — conversation should still be there
