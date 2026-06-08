# Phase 4: Root-Cause Architecture Fixes — Backend Event Pipeline + Macro Graph Decomposition + Token Accounting

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the remaining architectural root causes — unreliable event pipeline, monolithic macro graph, missing token accounting — that produce bugs no amount of surface-level patching can eliminate.

**Architecture:** Three pillars: (1) Event pipeline hardening with priority, backpressure, and reliable emission; (2) Macro graph decomposition from 1,119-line monolith into focused modules; (3) Token accounting aggregation for sub-agents and cost visibility. Frontend cache deduplication is a bonus task.

**Tech Stack:** Python asyncio, LangGraph, Pydantic AI, EventBus, TypeScript Zustand

---

## Root Cause Analysis

### RC1: Event Pipeline Is "Best Effort" Not "Reliable" — Silent Data Loss Is Inevitable

**Current state:**
- `bus.py:154-162` — Buffer overflow silently drops old events (`self._buffer = self._buffer[-self._buffer_size:]`)
- `bus.py:161` — Subscriber queue full → drops with `logger.warning` only
- `llm_executor.py` — `_bus.emit()` calls have no try-catch; bus=None is a silent no-op
- No priority system: `workflow.completed` and `agent.text_delta` compete for the same queue

**Why this is root cause:**
The event pipeline is the backbone of the entire real-time system. Without architectural guarantees, any downstream symptom (lost messages, stale UI, missing charts) is a random artifact of timing, not a fixable bug.

**Design principles violated:** Reliability, Priority Inversion Prevention, Separation of Concerns

---

### RC2: Macro Graph Violates SRP — 1,119 Lines Mixing 6+ Concerns

**Current structure:**
```
Lines 1-130:   Stop/regenerate signal management
Lines 131-189: Schema validation utilities
Lines 190-487: MacroGraphBuilder class (build, config resolution)
Lines 488-530: _make_node_func setup (prompt augmentation, tool info)
Lines 530-1074: node_func closure (550 lines!) — execution, retry, interrupt, error, emit
Lines 1075-1119: Passthrough node + routing helpers
```

**Why this is root cause:**
The 550-line `node_func` closure is the same anti-pattern that `workflowStores.ts` had before Phase 2 fixed it. It mixes extension coordination, error handling, interrupt logic, event emission, retry, and state management into a single function. This makes testing impossible, debugging difficult, and every new feature adds risk.

**Design principles violated:** SRP, Testability, Separation of Concerns

---

### RC3: Token Accounting Has No Aggregation Architecture

**Current state:**
- `llm_executor.py:888-912` — Tracks only top-level agent tokens
- `harness/tools/sub_agent.py` — Sub-agent usage is completely invisible
- `CHANGELOG.md` explicitly notes: "Sub-agent token usage not counted"
- No distinction between input/output/reasoning/cache-hit tokens

**Why this is root cause:**
Token costs are a first-class concern in production LLM systems. Without an aggregation architecture, every new multi-agent feature (sub-agents, eval retries, critiques) silently adds untracked cost. This is not a "bug to fix" — it's a "capability to build."

**Design principles violated:** Observability, Complete Cost Visibility

---

### RC4: Frontend Cache Management Is Copy-Paste (Minor)

**Current state:**
- 3 stores (conversation, workflow, output) each have 4 nearly identical cache methods
- 24 total occurrences of saveToCache/restoreFromCache/setActiveWid/clearCache
- Each store caches its own state shape, but the pattern is identical

**Note:** RAF batching and ID counters are already extracted to shared libs. Cache management is the last remaining cross-cutting duplication.

**Design principles violated:** DRY

---

## Root Cause Dependency Graph

```
RC1: Event Pipeline (most fundamental — everything depends on reliable events)
 ↓
RC2: Macro Graph Decomposition (relies on reliable events for clean extraction)
 ↓ (can parallel with)
RC3: Token Accounting (independent of graph structure)
 ↓ (bonus)
RC4: Frontend Cache Dedup (independent, low risk)
```

---

## Task Breakdown

### Task 1: Event Priority System — Critical vs Best-Effort Events

**Files:**
- Modify: `harness/extensions/bus.py:1-50`
- Test: `tests/test_event_priority.py` (new)

**Step 1: Write the failing test**

```python
"""Test event priority system."""
import asyncio
import pytest
from harness.extensions.bus import EventBus


@pytest.fixture
def bus():
    return EventBus(buffer_size=10)


def test_critical_event_never_dropped(bus):
    """Critical events must survive buffer overflow."""
    # Fill buffer with normal events
    for i in range(15):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    # Critical event should still be in buffer
    bus.emit("workflow.completed", {"workflow_id": "w1"}, priority="critical")
    buffered = bus.get_buffered_events()
    critical = [e for e in buffered if e["type"] == "workflow.completed"]
    assert len(critical) == 1


def test_critical_event_goes_to_front_of_subscriber_queue(bus):
    """When subscriber queue is full, critical events bypass normal ones."""
    bus.subscribe("sub1")
    # Overflow subscriber queue
    for i in range(bus._buffer_size + 5):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    bus.emit("node.failed", {"node_id": "n1", "error": "crash"}, priority="critical")

    events = []
    q = bus._subscribers["sub1"]
    while not q.empty():
        events.append(q.get_nowait())

    failed = [e for e in events if e["type"] == "node.failed"]
    assert len(failed) == 1


def test_normal_events_dropped_fifo(bus):
    """Normal events are dropped oldest-first when buffer overflows."""
    bus.emit("agent.text_delta", {"text": "first"})
    for i in range(bus._buffer_size):
        bus.emit("agent.text_delta", {"text": f"fill-{i}"})
    bus.emit("agent.text_delta", {"text": "last"})

    buffered = bus.get_buffered_events()
    texts = [e["payload"]["text"] for e in buffered if e["type"] == "agent.text_delta"]
    assert "first" not in texts
    assert "last" in texts
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_priority.py -v`
Expected: FAIL — `emit()` doesn't accept `priority` parameter

**Step 3: Implement priority support in EventBus**

Add `priority` parameter to `emit()` and separate internal buffers:

```python
# In bus.py, modify the emit method signature:
def emit(
    self,
    event_type: str,
    payload: dict | None = None,
    *,
    priority: Literal["normal", "critical"] = "normal",
    metadata: dict | None = None,
) -> None:
```

Implementation strategy:
- Maintain two internal lists: `_buffer` (normal) and `_critical_buffer` (critical)
- `_critical_buffer` has a smaller, separate limit (default 100, no eviction)
- `get_buffered_events()` returns critical first, then normal
- Subscriber dispatch: critical events go first in queue, normal events may be dropped

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_priority.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/bus.py tests/test_event_priority.py
git commit -m "feat: event priority system — critical events survive buffer overflow"
```

---

### Task 2: Reliable Event Emission — Guard All emit() Calls

**Files:**
- Modify: `harness/engine/llm_executor.py` (all `self._bus.emit()` calls)
- Modify: `harness/engine/macro_graph.py` (all `bus.emit()` calls)
- Test: `tests/test_event_emission_robustness.py` (new)

**Step 1: Write the failing test**

```python
"""Test that event emission failures don't crash the pipeline."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from harness.extensions.bus import EventBus


def test_emit_failure_doesnt_crash():
    """If bus.emit raises, the node should still complete."""
    bus = EventBus()
    bus.emit = MagicMock(side_effect=RuntimeError("bus broken"))

    # Node execution should not raise even if emit fails
    # This tests the guard wrapper
    from harness.extensions.bus import safe_emit
    safe_emit(bus, "test.event", {"data": 1})  # Should not raise


def test_emit_with_none_bus():
    """safe_emit with None bus is a no-op, not a crash."""
    from harness.extensions.bus import safe_emit
    safe_emit(None, "test.event", {"data": 1})  # Should not raise
```

**Step 2: Implement safe_emit helper**

In `harness/extensions/bus.py`, add:

```python
def safe_emit(
    bus: EventBus | None,
    event_type: str,
    payload: dict | None = None,
    *,
    priority: Literal["normal", "critical"] = "normal",
    metadata: dict | None = None,
) -> None:
    """Emit event with full error handling. Never raises."""
    if bus is None:
        return
    try:
        bus.emit(event_type, payload, priority=priority, metadata=metadata)
    except Exception:
        logger.exception(f"Event emission failed: {event_type}")
```

**Step 3: Replace raw emit calls in llm_executor.py**

Replace all `self._bus.emit(...)` calls with `safe_emit(self._bus, ...)`.

**Step 4: Replace raw emit calls in macro_graph.py**

Replace all `bus.emit(...)` calls with `safe_emit(bus, ...)`.

**Step 5: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add harness/extensions/bus.py harness/engine/llm_executor.py harness/engine/macro_graph.py tests/test_event_emission_robustness.py
git commit -m "fix: safe_emit wrapper — event failures never crash the pipeline"
```

---

### Task 3: Macro Graph Decomposition — Extract Stop/Regenerate Signal Module

**Files:**
- Create: `harness/engine/stop_signal.py`
- Modify: `harness/engine/macro_graph.py:1-130`
- Test: `tests/harness/engine/test_stop_signal.py` (new)

**Step 1: Write the failing test**

```python
"""Test stop/regenerate signal management as an isolated module."""
import pytest
import asyncio
from harness.engine.stop_signal import StopSignalManager


@pytest.fixture
def mgr():
    return StopSignalManager()


def test_store_and_consume(mgr):
    mgr.store("wf1", "agent1", "partial output", "guidance")
    signal = mgr.consume("wf1")
    assert signal is not None
    assert signal["agent_name"] == "agent1"
    assert signal["partial_output"] == "partial output"
    assert signal["user_guidance"] == "guidance"


def test_consume_twice_returns_none(mgr):
    mgr.store("wf1", "agent1", "out", "")
    mgr.consume("wf1")
    assert mgr.consume("wf1") is None


def test_has_pending(mgr):
    assert not mgr.has_pending("wf1", "agent1")
    mgr.store("wf1", "agent1", "out", "")
    assert mgr.has_pending("wf1", "agent1")


def test_ttl_expiry(mgr):
    mgr = StopSignalManager(ttl_seconds=0)  # Immediate expiry
    mgr.store("wf1", "agent1", "out", "")
    import time
    time.sleep(0.1)
    assert mgr.consume("wf1") is None


@pytest.mark.asyncio
async def test_await_guidance():
    mgr = StopSignalManager()
    mgr.store("wf1", "agent1", "out", "")
    # Provide guidance after a short delay
    async def provide():
        await asyncio.sleep(0.05)
        await mgr.provide_guidance("wf1", "new guidance")

    asyncio.create_task(provide())
    guidance = await mgr.await_guidance("wf1", timeout=1.0)
    assert guidance == "new guidance"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/harness/engine/test_stop_signal.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Extract StopSignalManager to `harness/engine/stop_signal.py`**

Move lines 29-130 from `macro_graph.py` into a focused module:
- `StopSignalManager` class with `store`, `consume`, `has_pending`, `await_guidance`, `provide_guidance`, `clear` methods
- TTL-based expiry via `_get_stop_regen_ttl()`
- `_active_managers` dict instead of `_active_builders`
- Clean async API with `asyncio.Event` for guidance waiting

**Step 4: Update macro_graph.py to use StopSignalManager**

Replace the in-class stop/regenerate methods with delegation to `StopSignalManager`:
```python
from harness.engine.stop_signal import StopSignalManager

class MacroGraphBuilder:
    def __init__(self, ...):
        self._signal_mgr = StopSignalManager()
```

**Step 5: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add harness/engine/stop_signal.py harness/engine/macro_graph.py tests/harness/engine/test_stop_signal.py
git commit -m "refactor: extract StopSignalManager from macro_graph — 130 lines → focused module"
```

---

### Task 4: Macro Graph Decomposition — Extract Node Execution Phases

**Files:**
- Create: `harness/engine/node_phases.py`
- Modify: `harness/engine/macro_graph.py:488-1074`
- Test: `tests/harness/engine/test_node_phases.py` (new)

**Step 1: Analyze the node_func closure phases**

The 550-line `node_func` closure has 6 distinct phases:

```
Phase 1: Pre-execution checks    (~50 lines)
  - Check upstream errors → skip
  - Build extension context
  - Emit node.started

Phase 2: Tool setup              (~30 lines)
  - Resolve tools
  - Create AgentDeps
  - Setup todo reminder tracker

Phase 3: LLM execution loop      (~200 lines)
  - Run agent via MicroAgentFactory
  - Handle retries
  - Handle interrupt/stop signals

Phase 4: Post-execution          (~100 lines)
  - Validate output
  - Run extension hooks (on_node_complete)
  - Update state

Phase 5: Error handling          (~80 lines)
  - Catch exceptions
  - Emit node.failed
  - Write to state.errors

Phase 6: Cleanup                 (~30 lines)
  - Unregister active builder
  - Emit node.completed
```

**Step 2: Write the failing test for pre-execution checks**

```python
"""Test node execution phases as isolated, testable functions."""
import pytest
from harness.engine.node_phases import check_upstream_errors, NodeSkipResult


def test_check_upstream_errors_all_clean():
    """No upstream errors → proceed with execution."""
    state = {"errors": {}, "outputs": {}}
    result = check_upstream_errors(state, ["dep1", "dep2"])
    assert result is None  # None = proceed


def test_check_upstream_errors_found():
    """Upstream error → skip with error info."""
    state = {
        "errors": {"dep1": {"error": "timeout"}},
        "outputs": {},
    }
    result = check_upstream_errors(state, ["dep1", "dep2"])
    assert result is not None
    assert isinstance(result, NodeSkipResult)
    assert result.failed_dep == "dep1"


def test_check_upstream_errors_no_deps():
    """No dependencies → always proceed."""
    state = {"errors": {"other": {"error": "fail"}}, "outputs": {}}
    result = check_upstream_errors(state, [])
    assert result is None
```

**Step 3: Extract phases to `harness/engine/node_phases.py`**

```python
"""Node execution phases — extracted from macro_graph.py node_func closure.

Each phase is a pure function or class that can be tested independently.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class NodeSkipResult:
    """Returned when a node should be skipped due to upstream failure."""
    failed_dep: str
    error_info: dict


def check_upstream_errors(
    state: dict,
    upstream_deps: list[str],
) -> NodeSkipResult | None:
    """Check if any upstream dependency has errors.
    Returns None if execution should proceed, or a skip result.
    """
    errors = state.get("errors", {})
    for dep_name in upstream_deps:
        if dep_name in errors:
            return NodeSkipResult(failed_dep=dep_name, error_info=errors[dep_name])
    return None


def build_extension_context(
    agent_def, parsed, config, workflow_id: str, node_id: str,
    event_bus, upstream_outputs: dict,
) -> dict:
    """Build the extension context for a node execution."""
    # ... extracted from lines 530-560 of macro_graph.py


def validate_and_process_output(
    raw_output: Any,
    result_type: type | None,
    retries: int,
    current_retry: int,
) -> tuple[Any, bool]:
    """Validate output against result_type.
    Returns (processed_output, should_retry).
    """
    # ... extracted from lines 800-900 of macro_graph.py


def emit_node_started(event_bus, workflow_id: str, node_id: str,
                      agent_name: str, model: str | None = None) -> None:
    """Emit node.started event with standard fields."""


def emit_node_completed(event_bus, workflow_id: str, node_id: str,
                        agent_name: str, output: Any, duration_ms: float,
                        token_usage: dict | None = None) -> None:
    """Emit node.completed event with standard fields."""


def emit_node_failed(event_bus, workflow_id: str, node_id: str,
                     agent_name: str, error: str, duration_ms: float) -> None:
    """Emit node.failed event with standard fields."""
```

**Step 4: Refactor macro_graph.py _make_node_func to use extracted phases**

Replace the monolithic closure with calls to the extracted functions:

```python
def _make_node_func(self, agent_def, parsed, dep_map, workflow_dir, ...):
    # ... setup code (50 lines, unchanged) ...

    async def nodeFunc(state):
        t0 = time.monotonic()

        # Phase 1: Pre-execution checks
        skip = check_upstream_errors(state, upstream_names)
        if skip:
            emit_node_failed(bus, workflow_id, node_id, agent_def.name,
                           f"Upstream dependency '{skip.failed_dep}' failed", 0)
            return state

        emit_node_started(bus, workflow_id, node_id, agent_def.name, model)

        # Phase 2: Tool setup
        deps, reminder_tracker = setup_tools(...)

        # Phase 3: Execution loop
        for attempt in range(retries + 1):
            result = await execute_agent(...)

        # Phase 4: Output validation
        output, should_retry = validate_and_process_output(...)

        # Phase 5-6: Error handling + cleanup
        ...
```

**Step 5: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add harness/engine/node_phases.py harness/engine/macro_graph.py tests/harness/engine/test_node_phases.py
git commit -m "refactor: extract node execution phases from macro_graph — testable, focused functions"
```

---

### Task 5: Macro Graph Decomposition — Extract Schema Validation

**Files:**
- Create: `harness/engine/schema_utils.py`
- Modify: `harness/engine/macro_graph.py:131-189`
- Test: `tests/harness/engine/test_schema_utils.py` (new)

**Step 1: Write the failing test**

```python
"""Test schema validation utilities."""
import pytest
from pydantic import BaseModel
from harness.engine.schema_utils import strip_schema, validate_output


class SimpleModel(BaseModel):
    name: str
    value: int


class NestedModel(BaseModel):
    items: list[SimpleModel]


def test_strip_schema_removes_title():
    schema = SimpleModel.model_json_schema()
    assert "title" in schema
    stripped = strip_schema(schema)
    assert "title" not in stripped


def test_strip_schema_removes_anyof_null():
    """Optional[SimpleModel] generates anyOf with null — should be simplified."""
    schema = {
        "anyOf": [
            {"$ref": "#/$defs/SimpleModel"},
            {"type": "null"}
        ],
        "$defs": {"SimpleModel": {"properties": {"name": {"type": "string"}}}}
    }
    stripped = strip_schema(schema)
    # Should resolve to just the model ref or the non-null variant
    assert "anyOf" not in stripped or len(stripped.get("anyOf", [])) == 1


def test_validate_output_valid():
    result = validate_output('{"name": "test", "value": 42}', SimpleModel)
    assert result.name == "test"
    assert result.value == 42


def test_validate_output_invalid_returns_none():
    result = validate_output("not json at all", SimpleModel)
    assert result is None


def test_validate_output_dict_input():
    result = validate_output({"name": "test", "value": 42}, SimpleModel)
    assert result is not None
    assert result.name == "test"


def test_validate_output_none_type():
    """When result_type is None, return the raw output."""
    result = validate_output("anything", None)
    assert result == "anything"
```

**Step 2: Extract schema utilities to `harness/engine/schema_utils.py`**

Move `_strip_schema()`, `_validate_output()`, and `ReviewDecision` from `macro_graph.py:131-189` into the new module.

**Step 3: Update macro_graph.py imports**

```python
from harness.engine.schema_utils import strip_schema, validate_output, ReviewDecision
```

**Step 4: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 5: Commit**

```bash
git add harness/engine/schema_utils.py harness/engine/macro_graph.py tests/harness/engine/test_schema_utils.py
git commit -m "refactor: extract schema validation from macro_graph — standalone, tested module"
```

---

### Task 6: Token Accounting Architecture — Usage Aggregator

**Files:**
- Create: `harness/engine/token_aggregator.py`
- Modify: `harness/engine/llm_executor.py:888-912`
- Modify: `harness/tools/sub_agent.py`
- Test: `tests/harness/engine/test_token_aggregator.py` (new)

**Step 1: Write the failing test**

```python
"""Test token usage aggregation across agents and sub-agents."""
import pytest
from harness.engine.token_aggregator import TokenAggregator


def test_single_agent_usage():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    result = agg.get_totals()
    assert result["input"] == 100
    assert result["output"] == 50
    assert result["total"] == 150


def test_sub_agent_usage_aggregated():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.record("agent1.sub1", input_tokens=30, output_tokens=20)
    agg.record("agent1.sub2", input_tokens=40, output_tokens=10)
    result = agg.get_totals()
    assert result["input"] == 170  # 100 + 30 + 40
    assert result["output"] == 80   # 50 + 20 + 10


def test_per_agent_breakdown():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.record("agent2", input_tokens=200, output_tokens=100)
    breakdown = agg.get_breakdown()
    assert breakdown["agent1"]["total"] == 150
    assert breakdown["agent2"]["total"] == 300


def test_cache_hit_tracking():
    """Cache hit tokens should be tracked separately."""
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50, cache_hit_tokens=70)
    result = agg.get_totals()
    assert result["input"] == 100
    assert result["cache_hit"] == 70


def test_reset():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.reset()
    assert agg.get_totals()["total"] == 0
```

**Step 2: Implement TokenAggregator**

```python
"""Token usage aggregator — tracks per-agent and total token consumption.

Aggregates usage from primary agents AND sub-agents into a unified view.
Thread-safe via asyncio.Lock for concurrent workflow execution.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field


@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenAggregator:
    """Accumulates token usage across agents and sub-agents."""

    def __init__(self) -> None:
        self._usage: dict[str, AgentUsage] = {}

    def record(
        self,
        agent_name: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_hit_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        if agent_name not in self._usage:
            self._usage[agent_name] = AgentUsage()
        u = self._usage[agent_name]
        u.input_tokens += input_tokens
        u.output_tokens += output_tokens
        u.cache_hit_tokens += cache_hit_tokens
        u.reasoning_tokens += reasoning_tokens

    def get_totals(self) -> dict[str, int]:
        totals = AgentUsage()
        for u in self._usage.values():
            totals.input_tokens += u.input_tokens
            totals.output_tokens += u.output_tokens
            totals.cache_hit_tokens += u.cache_hit_tokens
            totals.reasoning_tokens += u.reasoning_tokens
        return {
            "input": totals.input_tokens,
            "output": totals.output_tokens,
            "total": totals.total,
            "cache_hit": totals.cache_hit_tokens,
            "reasoning": totals.reasoning_tokens,
        }

    def get_breakdown(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "input": u.input_tokens,
                "output": u.output_tokens,
                "total": u.total,
                "cache_hit": u.cache_hit_tokens,
                "reasoning": u.reasoning_tokens,
            }
            for name, u in self._usage.items()
        }

    def reset(self) -> None:
        self._usage.clear()
```

**Step 3: Integrate with llm_executor.py**

Add a `TokenAggregator` parameter to `LLMExecutor.__init__` and record usage after each agent run:

```python
# In the token recording block after agent execution:
if self._token_aggregator:
    self._token_aggregator.record(
        agent_name,
        input_tokens=usage_obj.input_tokens,
        output_tokens=usage_obj.output_tokens,
        cache_hit_tokens=getattr(usage_obj, 'cache_hit_tokens', 0) or 0,
        reasoning_tokens=getattr(usage_obj, 'reasoning_tokens', 0) or 0,
    )
```

**Step 4: Integrate with sub_agent.py**

After sub-agent execution, record its usage into the parent's aggregator:

```python
# In sub_agent.py, after executing the child agent:
if parent_aggregator and hasattr(agent_run, 'usage'):
    parent_aggregator.record(
        f"{parent_name}.sub.{child_name}",
        input_tokens=agent_run.usage.input_tokens,
        output_tokens=agent_run.usage.output_tokens,
    )
```

**Step 5: Emit token usage in node.completed event**

Add `token_breakdown` to the `node.completed` event payload when aggregator is available.

**Step 6: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 7: Commit**

```bash
git add harness/engine/token_aggregator.py harness/engine/llm_executor.py harness/tools/sub_agent.py tests/harness/engine/test_token_aggregator.py
git commit -m "feat: TokenAggregator — unified token accounting across agents and sub-agents"
```

---

### Task 7: Event Pipeline Backpressure — Emitter Throttling

**Files:**
- Modify: `harness/extensions/bus.py`
- Modify: `harness/engine/llm_executor.py` (agent.text_delta emission)
- Test: `tests/test_event_backpressure.py` (new)

**Step 1: Write the failing test**

```python
"""Test event pipeline backpressure — slow consumers shouldn't cause OOM."""
import pytest
import asyncio
from harness.extensions.bus import EventBus


@pytest.mark.asyncio
async def test_subscriber_backpressure():
    """When subscriber is slow, events should be dropped (not buffered infinitely)."""
    bus = EventBus(buffer_size=100, subscriber_queue_size=5)
    sub_id = bus.subscribe("slow_sub")

    # Rapidly emit 50 events — subscriber queue can only hold 5
    for i in range(50):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    q = bus._subscribers[sub_id]
    assert q.qsize() <= 10  # Queue + some slack, not 50


def test_buffer_size_limit_respected():
    """Internal buffer should not exceed configured size."""
    bus = EventBus(buffer_size=10)
    for i in range(100):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    buffered = bus.get_buffered_events()
    assert len(buffered) <= 15  # Some slack for critical events
```

**Step 2: Add subscriber_queue_size to EventBus**

```python
def __init__(self, buffer_size=2000, subscriber_queue_size=100):
    self._buffer_size = buffer_size
    self._subscriber_queue_size = subscriber_queue_size
    # ...
```

**Step 3: Throttle text_delta emission in llm_executor.py**

When the bus buffer is approaching capacity, coalesce text_delta events:

```python
# In the text_delta emission path:
if self._bus and hasattr(self._bus, 'buffer_usage'):
    if self._bus.buffer_usage() > 0.8:
        # Skip every other text_delta when under pressure
        if self._delta_counter % 2 == 0:
            self._delta_counter += 1
            return
        self._delta_counter = 0
```

**Step 4: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 5: Commit**

```bash
git add harness/extensions/bus.py harness/engine/llm_executor.py tests/test_event_backpressure.py
git commit -m "feat: event pipeline backpressure — bounded queues + delta throttling"
```

---

### Task 8: Frontend Cache Management Deduplication

**Files:**
- Create: `frontend/src/lib/storeCache.ts`
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts`
- Modify: `frontend/src/contexts/workflow-context/stores/workflow.ts`
- Modify: `frontend/src/contexts/workflow-context/stores/output.ts`

**Step 1: Write the shared cache utility**

```typescript
// frontend/src/lib/storeCache.ts
import type { StoreApi } from "zustand/vanilla";

/**
 * Cache management mixin for scoped stores.
 * Eliminates copy-paste across conversation/workflow/output stores.
 */
export function withCache<TState extends Record<string, unknown>>(
  store: StoreApi<TState>,
  options: {
    extractSnapshot: (state: TState) => Record<string, unknown>;
    applySnapshot: (state: TState, snap: Record<string, unknown>) => Partial<TState>;
  },
) {
  type CacheEntry = Record<string, unknown>;
  let _cache: Record<string, CacheEntry> = {};
  let _activeWid: string | null = null;

  return {
    saveToCache: (wid: string) => {
      const snap = options.extractSnapshot(store.getState());
      _cache = { ..._cache, [wid]: snap };
      // Also persist to store state for serialization
      store.setState({ _cache, _activeWid: wid } as unknown as Partial<TState>);
    },

    restoreFromCache: (wid: string): boolean => {
      const snap = _cache[wid];
      if (!snap) return false;
      store.setState(options.applySnapshot(store.getState(), snap));
      _activeWid = wid;
      return true;
    },

    setActiveWid: (wid: string | null) => {
      // Save current before switching
      if (_activeWid && _activeWid !== wid) {
        const snap = options.extractSnapshot(store.getState());
        _cache = { ..._cache, [_activeWid]: snap };
      }
      _activeWid = wid;
      if (wid && _cache[wid]) {
        store.setState(options.applySnapshot(store.getState(), _cache[wid]));
      }
      store.setState({ _activeWid: wid } as unknown as Partial<TState>);
    },

    clearCache: () => {
      _cache = {};
      _activeWid = null;
      store.setState({ _cache: {}, _activeWid: null } as unknown as Partial<TState>);
    },

    getCacheForWid: (wid: string): CacheEntry | undefined => _cache[wid],

    updateCachedWid: (wid: string, updater: (cache: CacheEntry) => CacheEntry | void) => {
      if (!_cache[wid]) return;
      const result = updater(_cache[wid]);
      if (result) _cache[wid] = result;
    },
  };
}

export type StoreCache = ReturnType<typeof withCache>;
```

**Step 2: Refactor conversation.ts to use withCache**

Replace the inline saveToCache/restoreFromCache/setActiveWid/clearCache methods with the shared utility. The store still owns its state shape; `withCache` only provides the pattern.

**Step 3: Refactor workflow.ts and output.ts similarly**

**Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add frontend/src/lib/storeCache.ts frontend/src/contexts/workflow-context/stores/
git commit -m "refactor: extract shared store cache management — DRY across 3 stores"
```

---

### Task 9: Token Usage Frontend Display — Cost Visibility

**Files:**
- Create: `frontend/src/components/diagnostics/TokenBreakdown.tsx`
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`
- Modify: `frontend/src/types/events.ts` (NodeCompletedPayload)
- Modify: `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts`

**Step 1: Update NodeCompletedPayload type**

Add `token_breakdown` field:

```typescript
export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  output: unknown;
  duration_ms: number;
  token_usage?: {
    input: number;
    output: number;
    total: number;
  };
  token_breakdown?: {
    [agentName: string]: {
      input: number;
      output: number;
      total: number;
      cache_hit?: number;
      reasoning?: number;
    };
  };
}
```

**Step 2: Create TokenBreakdown component**

```tsx
// frontend/src/components/diagnostics/TokenBreakdown.tsx
import React from "react";

interface TokenBreakdownProps {
  breakdown: Record<string, {
    input: number;
    output: number;
    total: number;
    cache_hit?: number;
    reasoning?: number;
  }>;
}

export const TokenBreakdown = React.memo(function TokenBreakdown({ breakdown }: TokenBreakdownProps) {
  const agents = Object.entries(breakdown);
  if (agents.length === 0) return null;

  const totals = agents.reduce(
    (acc, [, u]) => ({
      input: acc.input + u.input,
      output: acc.output + u.output,
      cache_hit: acc.cache_hit + (u.cache_hit ?? 0),
      reasoning: acc.reasoning + (u.reasoning ?? 0),
    }),
    { input: 0, output: 0, cache_hit: 0, reasoning: 0 },
  );

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Token Usage</h4>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th className="text-left">Agent</th>
            <th className="text-right">Input</th>
            <th className="text-right">Output</th>
            <th className="text-right">Cache Hit</th>
            <th className="text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {agents.map(([name, usage]) => (
            <tr key={name} className={name.includes(".sub.") ? "text-muted-foreground" : ""}>
              <td className="font-mono">{name}</td>
              <td className="text-right">{usage.input.toLocaleString()}</td>
              <td className="text-right">{usage.output.toLocaleString()}</td>
              <td className="text-right">{(usage.cache_hit ?? 0).toLocaleString()}</td>
              <td className="text-right font-medium">{usage.total.toLocaleString()}</td>
            </tr>
          ))}
          <tr className="border-t font-medium">
            <td>Total</td>
            <td className="text-right">{totals.input.toLocaleString()}</td>
            <td className="text-right">{totals.output.toLocaleString()}</td>
            <td className="text-right">{totals.cache_hit.toLocaleString()}</td>
            <td className="text-right">{(totals.input + totals.output).toLocaleString()}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
});
```

**Step 3: Integrate into DiagnosticsPanel**

Add the TokenBreakdown component when `token_breakdown` data is available from the node.completed event.

**Step 4: Update nodeHandlers.ts to store breakdown**

In the `node.completed` handler, store `token_breakdown` in the workflow state.

**Step 5: Verify**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: No errors

**Step 6: Commit**

```bash
git add frontend/src/components/diagnostics/TokenBreakdown.tsx frontend/src/components/diagnostics/DiagnosticsPanel.tsx frontend/src/types/events.ts frontend/src/contexts/workflow-context/routing/nodeHandlers.ts
git commit -m "feat: token breakdown display — per-agent + sub-agent token visibility"
```

---

### Task 10: Final Verification — Build + Test + Macro Graph Line Count

**Step 1: Run Python tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 2: Verify macro_graph.py line count**

Run: `wc -l harness/engine/macro_graph.py`
Expected: Under 700 lines (was 1,119)

**Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 4: Verify no new circular dependencies**

Run: `cd frontend && npx madge --circular src/`
Expected: 0 circular dependencies

**Step 5: Commit frontend build**

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend after Phase 4 architecture fixes"
```

---

## Summary

| Task | Root Cause | What | Files |
|------|-----------|------|-------|
| 1 | RC1: Event pipeline | Priority system — critical events never dropped | `bus.py` |
| 2 | RC1: Event pipeline | `safe_emit` — emission failures never crash | `bus.py`, `llm_executor.py`, `macro_graph.py` |
| 3 | RC2: Macro graph | Extract StopSignalManager — 130 lines | `stop_signal.py`, `macro_graph.py` |
| 4 | RC2: Macro graph | Extract node execution phases — 550 lines | `node_phases.py`, `macro_graph.py` |
| 5 | RC2: Macro graph | Extract schema validation — 60 lines | `schema_utils.py`, `macro_graph.py` |
| 6 | RC3: Token accounting | TokenAggregator + sub-agent integration | `token_aggregator.py`, `llm_executor.py`, `sub_agent.py` |
| 7 | RC1: Event pipeline | Backpressure — bounded queues + throttling | `bus.py`, `llm_executor.py` |
| 8 | RC4: Frontend dedup | Shared cache management utility | `storeCache.ts`, 3 store files |
| 9 | RC3: Token accounting | Frontend token breakdown display | `TokenBreakdown.tsx`, `DiagnosticsPanel.tsx` |
| 10 | — | Final verification | — |

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| macro_graph.py lines | 1,119 | < 700 |
| Event loss on buffer overflow | Silent drops | Critical events preserved |
| Sub-agent token tracking | None | Fully aggregated |
| bus.emit() failure handling | Crashes or silent | `safe_emit` catches all |
| Frontend cache method duplication | 24 copies across 3 stores | Shared utility |
| New test coverage | — | 6 new test files, ~50 tests |

## Execution Order

```
Task 1  — Event priority              (45 min)  ← Foundation for reliable events
Task 2  — safe_emit                   (30 min)  ← Protects all emission sites
Task 3  — StopSignalManager           (60 min)  ← First macro_graph extraction
Task 5  — Schema utils                (30 min)  ← Quick extraction
Task 4  — Node phases                 (90 min)  ← Biggest extraction, needs care
Task 7  — Backpressure                (45 min)  ← After Tasks 1-2 are in place
Task 6  — TokenAggregator             (60 min)  ← Independent of graph decomposition
Task 8  — Frontend cache dedup        (30 min)  ← Independent
Task 9  — Token display               (30 min)  ← Depends on Task 6
Task 10 — Verify                      (15 min)
```

**Total: ~7 hours**
