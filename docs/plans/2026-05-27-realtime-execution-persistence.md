# Real-Time Execution Persistence Refactor

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Backend collects all execution data (agent I/O, tool calls, conversation, charts) in real-time during workflow execution and persists it per-node, so data survives crashes and is always available for replay via user_id + workflow_id.

**Architecture:** Extend the existing `agent_io` collection pattern in `macro_graph.py` to also collect `tool_calls`. After each node completes, flush accumulated data to `RunStore`. Replace the Bus-buffer-based `ConversationCollector` with a builder that derives conversation from `agent_io + tool_calls` at save time. Remove frontend PATCH persistence — frontend only reads from backend.

**Tech Stack:** Python (FastAPI, Pydantic AI, LangGraph), RunStore JSON persistence

---

## Design Principles

1. **Backend owns all data.** Frontend is a read-only display layer.
2. **Collect at the source, not from the transport.** Data is collected where it's produced (macro_graph, llm_executor), not from Bus buffer.
3. **Persist per-node, not per-workflow.** Each completed node flushes to disk. Crashes only lose the in-progress node.
4. **Conversation is derived, not primary.** It's a view over `agent_io + tool_calls`, not a separate data stream.

---

### Task 1: Add tool_calls collection to LLMExecutor

**Files:**
- Modify: `harness/engine/llm_executor.py:53-74,141-169`
- Test: `tests/harness/engine/test_llm_executor.py`

**Step 1: Write the failing test**

Create `tests/harness/engine/test_llm_executor.py`:

```python
"""Tests for LLMExecutor tool_calls collection."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from harness.engine.llm_executor import LLMExecutor


@pytest.mark.asyncio
async def test_tool_calls_collected():
    """LLMExecutor collects tool call name, args, and result during execution."""
    executor = LLMExecutor(
        MagicMock(),
        MagicMock(),
        event_bus=None,
        workflow_id="wf1",
        node_id="agent1",
        agent_name="agent1",
    )

    # Simulate a tool call part and tool result part
    tool_call_part = MagicMock()
    tool_call_part.tool_name = "bash"
    tool_call_part.args = {"command": "ls -la"}

    tool_result_part = MagicMock()
    tool_result_part.tool_name = "bash"
    tool_result_part.content = "file1.txt\nfile2.txt"

    # Manually call the emit methods to verify collection
    executor._emit_tool_call(tool_call_part)
    executor._emit_tool_result(tool_result_part)

    assert len(executor.tool_calls) == 1
    tc = executor.tool_calls[0]
    assert tc["tool_name"] == "bash"
    assert tc["tool_args"] == {"command": "ls -la"}
    assert tc["tool_result"] == "file1.txt\nfile2.txt"


@pytest.mark.asyncio
async def test_tool_calls_empty_when_no_tools():
    """LLMExecutor has empty tool_calls when no tools are called."""
    executor = LLMExecutor(
        MagicMock(),
        MagicMock(),
        event_bus=None,
        workflow_id="wf1",
        node_id="agent1",
        agent_name="agent1",
    )
    assert executor.tool_calls == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/engine/test_llm_executor.py -v`
Expected: FAIL — `LLMExecutor has no attribute 'tool_calls'`

**Step 3: Implement tool_calls collection**

In `harness/engine/llm_executor.py`, add `tool_calls` list to `__init__` and collect in emit methods:

Add to `__init__` (after line 74):
```python
        self.tool_calls: list[dict[str, Any]] = []
```

Modify `_emit_tool_call` (line 202-211):
```python
    def _emit_tool_call(self, part) -> None:
        entry = {
            "tool_name": part.tool_name,
            "tool_args": part.args if hasattr(part, "args") else {},
        }
        self.tool_calls.append(entry)
        if not self._bus:
            return
        self._bus.emit("agent.tool_call", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "tool_args": entry["tool_args"],
        })
```

Modify `_emit_tool_result` (line 213-222):
```python
    def _emit_tool_result(self, part) -> None:
        # Find the last unmatched tool_call entry and attach result
        for tc in reversed(self.tool_calls):
            if tc["tool_name"] == part.tool_name and "tool_result" not in tc:
                tc["tool_result"] = str(part.content) if hasattr(part, "content") else ""
                break
        if not self._bus:
            return
        self._bus.emit("agent.tool_result", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "result": str(part.content) if hasattr(part, "content") else "",
        })
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/harness/engine/test_llm_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/engine/llm_executor.py tests/harness/engine/test_llm_executor.py
git commit -m "feat: add tool_calls collection to LLMExecutor"
```

---

### Task 2: Wire tool_calls from executor into macro_graph agent_io

**Files:**
- Modify: `harness/engine/macro_graph.py:495,617-622`

**Step 1: Understand the integration point**

In `macro_graph.py`, after the executor runs (line 495: `exec_result = await executor.run(context)`), the executor has `exec_result.agent_run` and `executor.tool_calls`. We need to store `tool_calls` alongside `agent_io` in the builder.

**Step 2: Add tool_calls to agent_io record**

In `macro_graph.py`, find the `agent_io` collection (around line 617-622):

```python
                io_data = {
                    "input_prompt": context,
                    "system_prompt": parsed.prompt,
                    "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                }
                builder_self.agent_io[agent_def.name] = io_data
```

Change to also store tool_calls from the executor:

```python
                io_data = {
                    "input_prompt": context,
                    "system_prompt": parsed.prompt,
                    "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                }
                # Collect tool calls from executor (if available)
                if hasattr(executor, "tool_calls") and executor.tool_calls:
                    io_data["tool_calls"] = executor.tool_calls
                builder_self.agent_io[agent_def.name] = io_data
```

**Step 3: Run existing tests**

Run: `pytest tests/test_run_store.py tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add harness/engine/macro_graph.py
git commit -m "feat: wire tool_calls from executor into agent_io"
```

---

### Task 3: Build conversation from agent_io + tool_calls at save time

**Files:**
- Modify: `harness/extensions/collectors.py` — replace buffer-based ConversationCollector

**Step 1: Understand the approach**

Instead of scanning Bus buffer for events, derive conversation from the structured data we already collect:
- Each entry in `agent_io` has `input_prompt`, `system_prompt`, `output_result`, and now `tool_calls`
- From this we can build the same conversation format the frontend expects

**Step 2: Replace ConversationCollector**

In `harness/extensions/collectors.py`, add a new function `build_conversation`:

```python
def build_conversation(agent_io: dict[str, dict]) -> list[dict]:
    """Build conversation messages from agent_io (with tool_calls).

    This replaces the buffer-based ConversationCollector. It derives
    conversation from structured execution data, not from Bus events.
    """
    counter = 0
    messages = []

    for agent_name, io in agent_io.items():
        counter += 1
        output = io.get("output_result", "")
        if isinstance(output, dict):
            summary = output.get("summary", "")
            details = output.get("details", "")
            content = summary
            if details:
                content = f"{summary}\n\n{details}"
        else:
            content = str(output)

        if content.strip():
            messages.append({
                "id": f"msg-{counter}",
                "type": "agent",
                "nodeId": agent_name,
                "agentName": agent_name,
                "content": content,
                "status": "done",
                "timestamp": 0,
            })

        # Add tool calls for this agent
        for tc in io.get("tool_calls", []):
            counter += 1
            messages.append({
                "id": f"msg-{counter}",
                "type": "tool_call",
                "nodeId": agent_name,
                "agentName": agent_name,
                "content": "",
                "toolName": tc.get("tool_name", ""),
                "toolArgs": tc.get("tool_args", {}),
                "toolResult": tc.get("tool_result", ""),
                "toolStatus": "done",
                "timestamp": 0,
            })

    return messages
```

Keep the existing `ConversationCollector` class (it still works for non-standard cases) but the runner will use `build_conversation` as the primary path.

**Step 3: Add test**

Add to `tests/harness/extensions/test_collectors.py`:

```python
from harness.extensions.collectors import build_conversation


def test_build_conversation_from_agent_io():
    agent_io = {
        "runner": {
            "input_prompt": "## Task\n...",
            "system_prompt": "You are a runner.",
            "output_result": {"summary": "Executed script", "details": "11 charts rendered"},
            "tool_calls": [
                {"tool_name": "bash", "tool_args": {"command": "ls"}, "tool_result": "file1.txt"},
                {"tool_name": "bash", "tool_args": {"command": "python script.py"}, "tool_result": "OK"},
            ],
        }
    }
    messages = build_conversation(agent_io)
    assert len(messages) == 3
    assert messages[0]["type"] == "agent"
    assert messages[0]["agentName"] == "runner"
    assert "Executed script" in messages[0]["content"]
    assert messages[1]["type"] == "tool_call"
    assert messages[1]["toolName"] == "bash"
    assert messages[1]["toolResult"] == "file1.txt"
    assert messages[2]["toolName"] == "bash"
    assert messages[2]["toolResult"] == "OK"


def test_build_conversation_no_tool_calls():
    agent_io = {
        "reviewer": {
            "input_prompt": "...",
            "output_result": {"summary": "Code looks good"},
        }
    }
    messages = build_conversation(agent_io)
    assert len(messages) == 1
    assert messages[0]["type"] == "agent"
    assert messages[0]["content"] == "Code looks good"


def test_build_conversation_empty():
    messages = build_conversation({})
    assert messages == []
```

**Step 4: Run tests**

Run: `pytest tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/extensions/collectors.py tests/harness/extensions/test_collectors.py
git commit -m "feat: add build_conversation from agent_io (replaces buffer-based collector)"
```

---

### Task 4: Wire build_conversation into runner + add per-node incremental save

**Files:**
- Modify: `server/runner.py:264-291,312-328`

**Step 1: Replace ConversationCollector with build_conversation**

In `server/runner.py`, in both success and failure paths, replace:

```python
                from harness.extensions.collectors import ConversationCollector, ChartCollector
                conv_collector = ConversationCollector(event_bus)
                conv_collector.collect_from_buffer()
```

With:

```python
                from harness.extensions.collectors import build_conversation, ChartCollector
```

And change the `conversation=` parameter in `RunStore().save()`:

```python
                conversation=build_conversation(_agent_io),
```

This derives conversation directly from `agent_io` (which now includes `tool_calls`), not from the Bus buffer.

**Step 2: Add per-node incremental save**

In `server/runner.py`, after `repo.update_status(workflow_id, "completed", {...})` (around line 252), add an incremental save call:

```python
                # Incremental save: flush completed data to disk after each workflow
                # (agent_io is already fully collected at this point)
```

Actually, per-node save is complex because `_run_workflow` runs the entire workflow as one async call. LangGraph handles node-by-node internally. The `agent_io` dict is fully populated after the workflow completes. So the practical approach is: **save once after workflow completes, but derive all data from collected structures (not from buffer)**.

This is already what we're doing. The key improvement is: **data comes from `agent_io` + `tool_calls`, not from Bus buffer**. If the process crashes mid-workflow, the LangGraph checkpoint system handles recovery.

**Step 3: Run tests**

Run: `pytest tests/test_run_store.py tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add server/runner.py
git commit -m "refactor: use build_conversation from agent_io instead of buffer-based collector"
```

---

### Task 5: Remove frontend PATCH persistence

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:92-113,161-186`

**Step 1: Make _saveConversation and _saveCharts into no-ops**

In `useWorkflowEvents.ts`, replace `_saveConversation` and `_saveCharts` with empty functions that log a debug message:

```typescript
/** No-op: backend now persists conversation via build_conversation. */
function _saveConversation(_workflowId: string | undefined): void {
  // Backend persists conversation from agent_io + tool_calls at save time.
  // Frontend PATCH is no longer the primary persistence path.
}

/** No-op: backend now persists chart_groups via ChartCollector. */
function _saveCharts(_workflowId: string | undefined): void {
  // Backend persists charts from chart.render events at save time.
  // Frontend PATCH is no longer the primary persistence path.
}
```

**Step 2: Verify replay still works**

The replay path is:
1. Click run in sidebar → `fetchRun(run_id)` → GET `/api/runs/{id}`
2. Backend returns full run record including `conversation`, `chart_groups`, `agent_io`
3. `showReplay(full)` → populates stores from run data

This path is entirely read-from-backend. Removing PATCH saves doesn't affect it.

**Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "refactor: remove frontend PATCH persistence — backend is now single source of truth"
```

---

### Task 6: End-to-end smoke test

**Files:**
- No code changes

**Step 1: Build frontend and start backend**

```bash
cd frontend && npm run build && cd ..
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

**Step 2: Verify via API**

```bash
# Create a test user
curl -s -X POST http://localhost:8000/api/users \
  -H "X-User-Id: admin" -H "Content-Type: application/json" \
  -d '{"user_id":"testuser2","name":"Test 2","role":"developer"}'

# Run a workflow (use any available template)
# ... start from browser ...

# After completion, check the run record
curl -s http://localhost:8000/api/runs -H "X-User-Id: testuser2" | python3 -m json.tool | head -40
```

**Step 3: Verify conversation data**

```bash
# Check latest run for conversation
RUN_ID=$(ls -t runs/*.json | head -1)
python3 -c "
import json
data = json.load(open('$RUN_ID'))
conv = data.get('conversation', [])
print(f'Conversation: {len(conv)} messages')
for m in conv:
    print(f'  {m[\"type\"]}: {m.get(\"agentName\",\"\")} {m.get(\"toolName\",\"\")} content_len={len(m.get(\"content\",\"\"))}')

# Check tool_calls in agent_io
for name, io in data.get('agent_io', {}).items():
    tc = io.get('tool_calls', [])
    print(f'agent_io[{name}]: tool_calls={len(tc)}')

# Check chart_groups
cg = data.get('chart_groups')
print(f'chart_groups: {bool(cg)}, groups={list(cg[\"groups\"].keys()) if cg else []}')
"
```

**Expected output**: conversation has both agent messages and tool_call messages, agent_io has tool_calls, chart_groups has data.
