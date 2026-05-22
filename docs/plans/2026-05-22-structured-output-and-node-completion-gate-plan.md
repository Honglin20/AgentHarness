# Structured Output & Node Completion Gate — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Force all agents to produce structured output (separating result from reasoning), validate output completeness before allowing node transition, and harden interrupt signal handling to prevent race conditions.

**Architecture:** Three independent changes that compose together: (1) `AgentResult` default `result_type` replaces raw `str` output, (2) output validation gate in `_make_node_func` before return, (3) interrupt signal TTL + tool-stage detection + frontend local state on stop.

**Tech Stack:** Python/Pydantic (backend), TypeScript/Zustand (frontend), Pydantic AI, LangGraph

---

### Task 1: Add `AgentResult` model and make it the default `result_type`

**Files:**
- Modify: `harness/api.py:1-68`
- Modify: `harness/engine/macro_graph.py:204-224` (the `_resolve_agent_config` method)
- Test: `tests/test_api.py`

**Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
from harness.api import Agent, AgentResult

def test_agent_default_result_type_is_agent_result():
    """Agent with no result_type specified should use AgentResult."""
    agent = Agent("analyzer", after=[])
    # The default result_type should be AgentResult, not None
    assert agent.result_type is AgentResult

def test_agent_explicit_result_type_not_overridden():
    """Agent with explicit result_type should keep it."""
    from pydantic import BaseModel
    class CustomResult(BaseModel):
        approved: bool
    agent = Agent("reviewer", after=[], result_type=CustomResult)
    assert agent.result_type is CustomResult

def test_agent_result_model_fields():
    """AgentResult must have summary (required) and details (optional)."""
    r = AgentResult(summary="Found 3 issues")
    assert r.summary == "Found 3 issues"
    assert r.details is None

    r2 = AgentResult(summary="Done", details="See attached report")
    assert r2.details == "See attached report"

def test_agent_result_summary_required():
    """AgentResult without summary must fail validation."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentResult()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_api.py::test_agent_default_result_type_is_agent_result tests/test_api.py::test_agent_explicit_result_type_not_overridden tests/test_api.py::test_agent_result_model_fields tests/test_api.py::test_agent_result_summary_required -v`
Expected: FAIL — `AgentResult` not imported, `agent.result_type` is `None`

**Step 3: Write minimal implementation**

In `harness/api.py`, add `AgentResult` before the `Agent` class and change `__init__` default:

```python
class AgentResult(BaseModel):
    """Default result_type. Forces separation of conclusion from process."""
    summary: str
    details: str | None = None


class Agent:
    """Declarative agent definition."""

    def __init__(
        self,
        name: str,
        after: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        retries: int = 3,
        result_type: Type[BaseModel] | None = None,
        on_pass: str | None = None,
        on_fail: str | None = None,
        eval: bool = False,
    ):
        self.name = name
        self.after = after or []
        self.tools = tools
        self.model = model
        self.retries = retries
        # Default to AgentResult when no result_type specified
        self.result_type = result_type if result_type is not None else AgentResult
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.eval = eval
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_api.py::test_agent_default_result_type_is_agent_result tests/test_api.py::test_agent_explicit_result_type_not_overridden tests/test_api.py::test_agent_result_model_fields tests/test_api.py::test_agent_result_summary_required -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/api.py tests/test_api.py
git commit -m "feat: add AgentResult as default result_type for structured agent output"
```

---

### Task 2: Remove `result_type=None → str` fallback in MicroAgentFactory

**Files:**
- Modify: `harness/engine/micro_agent.py:33-63` (the `create` method)
- Test: `tests/engine/test_micro_agent.py`

**Step 1: Write the failing test**

Add to `tests/engine/test_micro_agent.py`:

```python
def test_create_default_result_type_uses_agent_result():
    """When result_type is not passed, factory should use AgentResult."""
    from harness.api import AgentResult
    factory = MicroAgentFactory()
    agent = factory.create(
        name="test",
        prompt="You are a test agent.",
        tools=[],
        model="openai:gpt-4o",
        retries=1,
        result_type=None,
    )
    # Pydantic AI agent's output_type should be AgentResult, not str
    assert agent._output_type is AgentResult
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_micro_agent.py::test_create_default_result_type_uses_agent_result -v`
Expected: FAIL — `agent._output_type` is `str`

**Step 3: Write minimal implementation**

In `harness/engine/micro_agent.py`, change the `create` method:

```python
def create(
    self,
    name: str,
    prompt: str,
    tools: list[str] | None,
    model: str | None,
    retries: int,
    result_type: Type[BaseModel] | None,
    deps: AgentDeps | None = None,
    exclude_tools: list[str] | None = None,
) -> PydanticAgent:
    from harness.api import AgentResult
    agent_model = model or DEFAULT_MODEL
    if not agent_model:
        raise RuntimeError(
            "No model configured. Set HARNESS_MODEL env var (e.g. 'gpt-4o') "
            "or pass model=... to Agent().\n"
            "Run: python config_llm.py  or  export HARNESS_MODEL='gpt-4o'"
        )

    resolved_tools = self.tool_registry.resolve(tools, exclude=exclude_tools)

    effective_result_type = result_type if result_type is not None else AgentResult
    client = LLMClient(model=agent_model) if model else LLMClient()
    agent = client.agent(
        system_prompt=prompt,
        output_type=effective_result_type,
        retries=retries,
        tools=resolved_tools,
        deps_type=AgentDeps,
    )

    return agent
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_micro_agent.py::test_create_default_result_type_uses_agent_result -v`
Expected: PASS

**Step 5: Run full micro_agent tests to check no regressions**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_micro_agent.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/engine/micro_agent.py tests/engine/test_micro_agent.py
git commit -m "feat: MicroAgentFactory uses AgentResult when result_type is None"
```

---

### Task 3: Update `_resolve_agent_config` to inject AgentResult default

**Files:**
- Modify: `harness/engine/macro_graph.py:204-224`
- Test: `tests/engine/test_macro_graph.py`

**Step 1: Write the failing test**

Add to `tests/engine/test_macro_graph.py`:

```python
def test_resolve_agent_config_default_result_type():
    """Agent with no result_type and no conditional edges should get AgentResult."""
    from harness.api import AgentResult
    from harness.compiler.md_parser import parse_agent_md
    from pathlib import Path

    agents = [Agent("analyzer", after=[])]
    workflow = _make_workflow(agents)
    builder = MacroGraphBuilder()
    builder.build(workflow)

    agent_def = agents[0]
    # Parse the agent MD
    md_path = Path(__file__).resolve().parent.parent / "compiler" / "fixtures" / "analyzer.md"
    if md_path.exists():
        parsed = parse_agent_md(md_path)
    else:
        # Use a minimal parsed result
        from unittest.mock import MagicMock
        parsed = MagicMock(tools=None, model=None, retries=3)

    tools, model, retries, result_type = builder._resolve_agent_config(agent_def, parsed)
    assert result_type is AgentResult


def test_resolve_agent_config_conditional_edges_get_review_decision():
    """Agent with conditional edges should get ReviewDecision, not AgentResult."""
    from harness.engine.macro_graph import ReviewDecision
    agents = [Agent("reviewer", after=[], on_fail="coder")]
    workflow = _make_workflow(agents)
    builder = MacroGraphBuilder()
    builder.build(workflow)

    agent_def = agents[0]
    from unittest.mock import MagicMock
    parsed = MagicMock(tools=None, model=None, retries=3)

    tools, model, retries, result_type = builder._resolve_agent_config(agent_def, parsed)
    assert result_type is ReviewDecision
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_resolve_agent_config_default_result_type -v`
Expected: FAIL — `result_type` is `None` because `agent_def.result_type` is already `AgentResult` from Task 1, but `_resolve_agent_config` still passes it through without explicit handling

Wait — after Task 1, `Agent.__init__` already sets `self.result_type = AgentResult` when `result_type=None` is passed. So `_resolve_agent_config` should already see `AgentResult`. Let me re-check...

After Task 1: `Agent("analyzer", after=[])` → `self.result_type = AgentResult`. So `_resolve_agent_config` reads `agent_def.result_type = AgentResult`. The existing code does `result_type = agent_def.result_type`, which is now `AgentResult` instead of `None`. The conditional edge auto-inject (`if agent_def.has_conditional_edges and result_type is None`) is fine because `result_type` is already `AgentResult` not `None`.

This means Task 3 is **already handled by Task 1** — no code change needed in `_resolve_agent_config`. The test should pass already after Task 1. Let me adjust:

**Step 2 (revised): Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_resolve_agent_config_default_result_type tests/engine/test_macro_graph.py::test_resolve_agent_config_conditional_edges_get_review_decision -v`
Expected: PASS (because Task 1 already made `agent_def.result_type = AgentResult`)

**Step 3: Commit the tests**

```bash
git add tests/engine/test_macro_graph.py
git commit -m "test: verify _resolve_agent_config returns AgentResult by default"
```

---

### Task 4: Add output completeness validation gate in `_make_node_func`

**Files:**
- Modify: `harness/engine/macro_graph.py:459-525` (after `output = agent_run.result.output`, before writing `result_dict`)
- Test: `tests/engine/test_macro_graph.py`

**Step 1: Write the failing test**

Add to `tests/engine/test_macro_graph.py`:

```python
def test_output_validation_gate_rejects_incomplete_basemodel():
    """Node function should return errors when BaseModel output fails validation."""
    from pydantic import BaseModel, ValidationError
    from harness.engine.macro_graph import _validate_output

    class StrictResult(BaseModel):
        summary: str
        score: float

    # A valid output should pass
    valid = StrictResult(summary="Done", score=0.9)
    assert _validate_output(valid, StrictResult) is None

    # Simulate an invalid output (summary missing) — this would come from
    # an interrupted agent that produced partial output
    # Since Pydantic AI wouldn't actually produce this, we test the validator
    # directly with a manually constructed broken object
    broken = StrictResult(summary="Done", score=float('nan'))
    # NaN is technically valid for float, so let's test with a different approach
    # We test that the validation function returns an error string when
    # model_validate raises ValidationError
    import unittest.mock as mock
    with mock.patch.object(StrictResult, 'model_validate', side_effect=ValidationError.from_exception_data("StrictResult", [])):
        result = _validate_output(broken, StrictResult)
        assert result is not None  # Should return an error string
        assert "validation" in result.lower() or "failed" in result.lower()


def test_output_validation_gate_accepts_valid_agent_result():
    """Valid AgentResult should pass the validation gate."""
    from harness.api import AgentResult
    from harness.engine.macro_graph import _validate_output

    valid = AgentResult(summary="Task completed successfully")
    assert _validate_output(valid, AgentResult) is None


def test_output_validation_gate_rejects_none_output():
    """None output should fail validation."""
    from harness.api import AgentResult
    from harness.engine.macro_graph import _validate_output

    result = _validate_output(None, AgentResult)
    assert result is not None
    assert "no output" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_output_validation_gate_rejects_incomplete_basemodel tests/engine/test_macro_graph.py::test_output_validation_gate_accepts_valid_agent_result tests/engine/test_macro_graph.py::test_output_validation_gate_rejects_none_output -v`
Expected: FAIL — `_validate_output` function doesn't exist yet

**Step 3: Write minimal implementation**

Add `_validate_output` function in `harness/engine/macro_graph.py`, before the `MacroGraphBuilder` class:

```python
from pydantic import ValidationError


def _validate_output(output: Any, result_type: Type[BaseModel] | None) -> str | None:
    """Validate agent output against its result_type.

    Returns None if valid, or an error string if validation fails.
    """
    if output is None:
        return "Agent produced no output (interrupted or failed)"
    if result_type is None:
        return None
    if not isinstance(output, BaseModel):
        return f"Expected {result_type.__name__}, got {type(output).__name__}"
    try:
        output.model_validate(output.model_dump())
    except ValidationError as e:
        return f"Output validation failed: {e}"
    return None
```

Then in `_make_node_func`, after the line `output = agent_run.result.output` (line 459) and before the `# === Extension hook/middleware: after_node ===` comment (line 464), insert:

```python
                # === Output completeness validation gate ===
                validation_error = _validate_output(output, result_type)
                if validation_error:
                    duration_ms = int((time.time() - start_time) * 1000)
                    if bus:
                        bus.emit("node.failed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": validation_error,
                            "duration_ms": duration_ms,
                            "attempt": 1,
                            "will_retry": False,
                        })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: validation_error},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_output_validation_gate_rejects_incomplete_basemodel tests/engine/test_macro_graph.py::test_output_validation_gate_accepts_valid_agent_result tests/engine/test_macro_graph.py::test_output_validation_gate_rejects_none_output -v`
Expected: PASS

**Step 5: Run full macro_graph tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/engine/macro_graph.py tests/engine/test_macro_graph.py
git commit -m "feat: add output completeness validation gate before node transition"
```

---

### Task 5: Add interrupt signal check during tool execution

**Files:**
- Modify: `harness/engine/macro_graph.py:382-421` (the `is_call_tools_node` branch)
- Test: `tests/engine/test_macro_graph.py`

**Step 1: Write the failing test**

Add to `tests/engine/test_macro_graph.py`:

```python
def test_has_pending_stop_regen_with_ttl():
    """Interrupt signal should expire after TTL."""
    import time
    from harness.engine.macro_graph import (
        request_stop_and_regenerate,
        _has_pending_stop_regen,
        _consume_stop_regen,
        _pending_stop_regen,
    )

    # Clean up any existing signals
    _pending_stop_regen.clear()

    # Fresh signal should be detected
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        request_stop_and_regenerate("test_wf_1", "agent_a", "partial", "guidance")
    )
    assert _has_pending_stop_regen("test_wf_1", "agent_a") is True

    # Signal for different agent should not match
    assert _has_pending_stop_regen("test_wf_1", "agent_b") is False

    # Signal for different workflow should not match
    assert _has_pending_stop_regen("test_wf_2", "agent_a") is False

    # Consume the signal
    consumed = _consume_stop_regen("test_wf_1")
    assert consumed is not None
    assert consumed["agent_name"] == "agent_a"
    assert _has_pending_stop_regen("test_wf_1", "agent_a") is False

    # Clean up
    _pending_stop_regen.clear()


def test_stop_regen_signal_ttl_expiry():
    """Interrupt signal older than 60 seconds should be expired and cleaned up."""
    import time
    from harness.engine.macro_graph import (
        request_stop_and_regenerate,
        _has_pending_stop_regen,
        _pending_stop_regen,
    )

    _pending_stop_regen.clear()

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        request_stop_and_regenerate("test_wf_ttl", "agent_a", "partial", "guidance")
    )

    # Manually backdate the timestamp to simulate expiry
    _pending_stop_regen["test_wf_ttl"]["_ts"] = time.time() - 61

    # Should be expired
    assert _has_pending_stop_regen("test_wf_ttl", "agent_a") is False
    # Signal should be cleaned up
    assert "test_wf_ttl" not in _pending_stop_regen

    _pending_stop_regen.clear()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_has_pending_stop_regen_with_ttl tests/engine/test_macro_graph.py::test_stop_regen_signal_ttl_expiry -v`
Expected: FAIL — `_has_pending_stop_regen` doesn't check TTL yet

**Step 3: Write minimal implementation**

In `harness/engine/macro_graph.py`, update `request_stop_and_regenerate` and `_has_pending_stop_regen`:

```python
_STOP_REGEN_TTL = 60  # seconds

_pending_stop_regen: dict[str, dict[str, str | float]] = {}  # workflow_id → {agent_name, partial_output, user_guidance, _ts}
_stop_regen_lock = asyncio.Lock()


async def request_stop_and_regenerate(
    workflow_id: str,
    agent_name: str,
    partial_output: str,
    user_guidance: str,
) -> None:
    """Called from WebSocket handler when user requests stop + regenerate."""
    async with _stop_regen_lock:
        _pending_stop_regen[workflow_id] = {
            "agent_name": agent_name,
            "partial_output": partial_output,
            "user_guidance": user_guidance,
            "_ts": time.time(),
        }


def _has_pending_stop_regen(workflow_id: str, agent_name: str) -> bool:
    pending = _pending_stop_regen.get(workflow_id)
    if pending is None:
        return False
    # TTL check — expire signals older than _STOP_REGEN_TTL seconds
    if time.time() - pending.get("_ts", 0) > _STOP_REGEN_TTL:
        _pending_stop_regen.pop(workflow_id, None)
        return False
    return pending.get("agent_name") == agent_name
```

Then in the `_run_agent` function, add interrupt check at the start of the `is_call_tools_node` branch (line 382):

```python
                            elif pydantic_agent.is_call_tools_node(node):
                                # Check interrupt signal before executing tools
                                if wid and _has_pending_stop_regen(wid, agent_def.name):
                                    stop_regen = _consume_stop_regen(wid)
                                    break

                                if bus:
                                    # ... existing tool execution logic ...
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_has_pending_stop_regen_with_ttl tests/engine/test_macro_graph.py::test_stop_regen_signal_ttl_expiry -v`
Expected: PASS

**Step 5: Run full macro_graph tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/engine/macro_graph.py tests/engine/test_macro_graph.py
git commit -m "feat: add interrupt check during tool execution + TTL for stop signals"
```

---

### Task 6: Frontend — Add `interrupted` status to conversationStore

**Files:**
- Modify: `frontend/src/stores/conversationStore.ts:1-205`
- Test: Manual verification in browser

**Step 1: Update the `ConversationMessage` type**

In `frontend/src/stores/conversationStore.ts`, change line 12:

```typescript
// Before:
  status?: "streaming" | "done" | "error";

// After:
  status?: "streaming" | "done" | "error" | "interrupted";
```

**Step 2: Add `interruptAgentMessage` and `resumeAgentMessage` actions**

Add to the `ConversationState` interface (after line 33):

```typescript
  interruptAgentMessage: (agentName: string) => void;
  resumeAgentMessage: (nodeId: string, agentName: string) => void;
```

Add implementations in the store (after `clearPendingQuestion`):

```typescript
  interruptAgentMessage: (agentName) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.type === "agent" && m.status === "streaming" && (m.agentName === agentName || m.nodeId === agentName)
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = { ...messages[idx], status: "interrupted" };
      return { messages };
    }),

  resumeAgentMessage: (nodeId, agentName) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.type === "agent" && m.status === "interrupted" && (m.nodeId === nodeId || m.agentName === agentName)
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = { ...messages[idx], status: "streaming" };
      return { messages };
    }),
```

**Step 3: Update `completeAgentMessage` and `failAgentMessage` to also match `interrupted` status**

Change `completeAgentMessage` (line 96-111) — the `findLastIndex` should match either `streaming` or `interrupted`:

```typescript
  completeAgentMessage: (nodeId, agentName, durationMs) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = {
        ...messages[idx],
        agentName,
        status: "done",
        durationMs,
      };
      return { messages };
    }),
```

Change `failAgentMessage` (line 113-129) similarly:

```typescript
  failAgentMessage: (nodeId, agentName, error, durationMs) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = {
        ...messages[idx],
        agentName,
        content: messages[idx].content + `\n\n**Error:** ${error}`,
        status: "error",
        durationMs,
      };
      return { messages };
    }),
```

**Step 4: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to conversationStore

**Step 5: Commit**

```bash
git add frontend/src/stores/conversationStore.ts
git commit -m "feat: add interrupted status + interruptAgentMessage/resumeAgentMessage to conversationStore"
```

---

### Task 7: Frontend — Wire up interrupt on Stop click and workflow.resumed event

**Files:**
- Modify: `frontend/src/components/chat/ChatInput.tsx:63-70`
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:176-183`

**Step 1: Update `handleStop` in ChatInput.tsx**

Change the `handleStop` callback (line 63-70):

```typescript
  const handleStop = useCallback(() => {
    if (!streamingAgent || !sendStopAndRegenerate) return;
    // Immediately mark agent as interrupted locally to prevent race conditions
    useConversationStore.getState().interruptAgentMessage(streamingAgent.agentName);
    sendStopAndRegenerate(streamingAgent.agentName, streamingAgent.content, value);
    if (value.trim()) {
      useConversationStore.getState().addUserMessage(value);
    }
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, value]);
```

**Step 2: Update `workflow.resumed` handler in useWorkflowEvents.ts**

Change the `workflow.resumed` case (line 176-183):

```typescript
    case "workflow.resumed": {
      const p = event.payload as { workflow_id: string; node_id: string; directive?: string };
      useConversationStore.getState().resumeAgentMessage(p.node_id, "");
      break;
    }
```

**Step 3: Update `streamingAgent` detection in ChatInput.tsx to also match `interrupted`**

The `streamingAgent` lookup (line 31-39) should also find `interrupted` agents so the Stop button shows while waiting for resume:

```typescript
  const streamingAgent = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")) {
        return { agentName: m.agentName ?? m.nodeId ?? "agent", content: m.content, status: m.status };
      }
    }
    return null;
  })();
```

Update `showStop` to only show for `streaming` (not `interrupted` — we're already stopping):

```typescript
  const showStop = !!streamingAgent && streamingAgent.status === "streaming" && !!sendStopAndRegenerate && !hasPendingQuestion;
```

**Step 4: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/components/chat/ChatInput.tsx frontend/src/hooks/useWorkflowEvents.ts
git commit -m "feat: wire up local interrupt state on Stop click and resumeAgentMessage on workflow.resumed"
```

---

### Task 8: Update existing agent MD prompts to use AgentResult format

**Files:**
- Modify: all `workflows/*/agents/*.md` files that don't specify `result_type`
- Modify: `workflows/_shared/agents/*.md`

**Step 1: Find all agent MD files**

Run: `find /Users/mozzie/Desktop/Projects/AgentHarness/workflows -name "*.md" -path "*/agents/*"`
List all agent MD files.

**Step 2: Add instruction to each agent's prompt**

For each agent MD file that doesn't have `result_type` in frontmatter, append a line to the prompt section instructing the model to output `AgentResult` format:

```markdown
Your output must be a JSON object with "summary" (required, concise conclusion) and "details" (optional, elaboration).
```

This is needed because Pydantic AI will now expect `AgentResult` output — the model needs to know the schema.

**Step 3: Commit**

```bash
git add workflows/
git commit -m "feat: update agent MD prompts to reference AgentResult output format"
```

---

### Task 9: Run full test suite and verify end-to-end

**Files:**
- No new files

**Step 1: Run backend tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/ -v --tb=short 2>&1 | tail -40`
Expected: ALL PASS (or only pre-existing failures)

**Step 2: Run frontend build**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds with no TypeScript errors

**Step 3: Manual smoke test**

Start the dev server, create a workflow with 2 agents, and verify:
1. First agent output is structured (summary + details)
2. Second agent receives only the structured output, not the full reasoning
3. Stop button during agent streaming immediately changes UI state
4. After stop, agent resumes with new output
5. Interrupting and letting the agent produce incomplete output → node fails, not passes to next

**Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: address issues from end-to-end verification"
```
