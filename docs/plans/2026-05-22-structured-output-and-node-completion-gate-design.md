# Structured Output & Node Completion Gate — Design

> Date: 2026-05-22

## Problem

Two issues with the current agent interaction model:

1. **Output bloat**: Agent outputs contain the full reasoning process (thousands of tokens of chain-of-thought, tool call results, intermediate conclusions). Downstream agents receive all of it via `## Output from X`, wasting context window and confusing the next agent.

2. **Flaky node transitions**: There is no validation that an agent has genuinely completed its task before the workflow moves to the next node. In particular:
   - Interrupted agents produce incomplete output that is still written to `state["outputs"]` and passed downstream.
   - `stop_and_regenerate` signal is only checked during text streaming, not during tool execution.
   - Orphan interrupt signals (agent already finished before signal was consumed) persist indefinitely.
   - Frontend has no local state transition on stop — creates a race window.

## Design

### §1 `AgentResult` — Default Structured Output Type

**Current**: `Agent(result_type=None)` → `output_type=str`. The entire LLM response (reasoning + conclusion) is one unstructured string.

**Change**: Introduce a default `AgentResult` model. When `result_type` is not specified, use `AgentResult` instead of `str`.

```python
class AgentResult(BaseModel):
    """Default result_type. Forces separation of conclusion from process."""
    summary: str                    # Concise conclusion — passed to downstream
    details: str | None = None      # Optional elaboration — also passed but agent may omit
```

**Downstream prompt change**: `build_node_prompt` already has an `isinstance(output, BaseModel)` branch that serializes to JSON. Since all outputs are now `BaseModel`, this branch becomes the only path:

```
## Output from analyzer
{"summary": "Found 3 issues: 1)... 2)... 3)...", "details": "1. Auth module lacks error handling..."}

## Output from coder
{"summary": "Modified 3 files", "details": "1. auth.py: added error handling..."}
```

**Custom `result_type`** is unchanged — `ReviewDecision`, `CodeReview`, etc. all use the same `BaseModel` serialization path.

**Breaking change**: Agents that previously returned raw `str` must now return `AgentResult` format. Acceptable at current project stage.

### §2 Output Completeness Validation Gate

Before a node function returns, validate the output against its `result_type`:

```python
# In _make_node_func, before writing result_dict
output = agent_run.result.output

if result_type is not None and isinstance(output, BaseModel):
    try:
        output.model_validate(output.model_dump())
    except ValidationError as e:
        # Validation failed → node failed, do NOT enter downstream
        return {
            STATE_OUTPUTS: {},
            STATE_ERRORS: {agent_def.name: f"Output validation failed: {e}"},
            STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
        }
```

**Interrupt incomplete output fails validation naturally**: When `stop_and_regenerate` breaks the `iter()` loop, `agent_run.result.output` is either:
- Not yet a valid `BaseModel` (parsing error) → validation catches it
- A partial `AgentResult` with `summary=None` → Pydantic `summary: str` (required) validation catches it

**After `stop_and_regenerate` retry**: If the retried agent produces a complete `AgentResult`, it passes validation and proceeds normally.

**Failed node behavior**: emit `node.failed` event. Does NOT auto-retry (distinct from `max_iterations` conditional-edge retry). User can re-run the workflow.

### §3 Interrupt Signal Hardening

#### 3.1 Check interrupt during tool execution

Current: only checked in `is_model_request_node` text streaming loop.

Change: also check before executing each tool-call batch:

```python
elif pydantic_agent.is_call_tools_node(node):
    # NEW: check interrupt before tool execution
    if wid and _has_pending_stop_regen(wid, agent_def.name):
        stop_regen = _consume_stop_regen(wid)
        break

    # ... existing tool execution logic ...
```

Note: a tool call already in-flight cannot be interrupted (Pydantic AI executes tools synchronously). We intercept before the next tool call starts.

#### 3.2 Interrupt signal TTL

Add timestamp to `_pending_stop_regen` entries. Expire after 60 seconds.

```python
_pending_stop_regen: dict[str, dict[str, str | float]] = {}

async def request_stop_and_regenerate(...):
    async with _stop_regen_lock:
        _pending_stop_regen[workflow_id] = {
            "agent_name": agent_name,
            "partial_output": partial_output,
            "user_guidance": user_guidance,
            "_ts": time.time(),
        }

def _has_pending_stop_regen(workflow_id, agent_name):
    pending = _pending_stop_regen.get(workflow_id)
    if pending is None:
        return False
    if time.time() - pending.get("_ts", 0) > 60:
        _pending_stop_regen.pop(workflow_id, None)
        return False
    return pending.get("agent_name") == agent_name
```

#### 3.3 Frontend local state on stop

When user clicks Stop, immediately mark the agent message locally before sending WebSocket:

```typescript
// ChatInput.tsx handleStop
const handleStop = () => {
    useConversationStore.getState().interruptAgentMessage(streamingAgent.agentName);
    sendStopAndRegenerate(streamingAgent.agentName, streamingAgent.content, value);
};
```

New `conversationStore` methods:

- `interruptAgentMessage(agentName)`: Find latest `status === "streaming"` message for this agent, set `status = "interrupted"`.
- `resumeAgentMessage(nodeId, agentName)`: Find `status === "interrupted"` message, set `status = "streaming"`.

New event handler:

```typescript
case "workflow.resumed": {
    const p = event.payload;
    useConversationStore.getState().resumeAgentMessage(p.node_id, p.agent_name);
    break;
}
```

The `interrupted` status: ChatInput shows a waiting state. On `workflow.resumed` → back to `streaming`. On `node.completed` → `done`. On `node.failed` → `failed`.

### §4 Prompt Passing Semantics (Summary)

| Scenario | Before | After |
|----------|--------|-------|
| Agent with no `result_type` | Full text (reasoning + conclusion) | `AgentResult` JSON (`summary` + `details`) |
| Agent with custom `result_type` | Custom BaseModel JSON | Same (no change) |
| Incomplete/interrupted output | Passed as-is to downstream | Validation fails → node failed |
| Judge pass-through | Passes raw output | Passes `AgentResult` or custom BaseModel (same mechanism) |

## Impact

### Files changed (backend)

| File | Change |
|------|--------|
| `harness/api.py` | Add `AgentResult` model; change `Agent.__init__` default `result_type` behavior |
| `harness/engine/macro_graph.py` | Add output validation gate in `_make_node_func`; add interrupt check in `is_call_tools_node`; add TTL to `_pending_stop_regen` |
| `harness/engine/micro_agent.py` | No change needed — `build_node_prompt` BaseModel branch already handles structured output |

### Files changed (frontend)

| File | Change |
|------|--------|
| `frontend/src/stores/conversationStore.ts` | Add `interruptAgentMessage()`, `resumeAgentMessage()`, add `"interrupted"` to message status type |
| `frontend/src/hooks/useWorkflowEvents.ts` | Add `workflow.resumed` handler calling `resumeAgentMessage` |
| `frontend/src/components/chat/ChatInput.tsx` | Call `interruptAgentMessage` in `handleStop` before sending WS |

### Breaking changes

- `Agent(result_type=None)` now produces `AgentResult` instead of `str`. Existing agents that return raw text need their prompts updated to instruct the model to output `summary` + `details`.
- The `"interrupted"` status is new — any frontend code that only expected `"streaming" | "done" | "failed"` needs updating.
