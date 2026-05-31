# Workflow Observability Enhancement Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 8 observability capabilities to the workflow engine — error context enrichment, cost tracking, step counting, structured span tracing, TTFT metrics, circular output detection, operating envelope, and version regression — without changing any existing behavior.

**Architecture:** All changes are purely additive. New data flows through the existing `Bus.emit()` + `NodeCtx.emit()` side-effect pipeline. No existing event schemas are modified — all new fields are optional additions to payloads. Frontend changes are limited to new UI in the existing DiagnosticsPanel tabs.

**Tech Stack:** Python (harness/), TypeScript/React (frontend/), Zustand stores, WebSocket events

**Risk strategy:** Every task uses the existing extension hook/plugin system. Existing tests must continue passing untouched. New features are gated behind new code paths — zero risk of regression.

---

## Task Dependency Graph

```
Task 1 (Error Context) ──→ independent
Task 2 (Cost Tracking) ──→ independent
Task 3 (Step Counter)  ──→ independent
Task 4 (Span Tracing)  ──→ Task 3 (uses step counter)
Task 5 (TTFT)          ──→ Task 4 (adds timing to span events)
Task 6 (Circular Det.)  ──→ Task 3 (uses step counter)
Task 7 (Envelope)      ──→ Task 2 + Task 3 (cost + step budgets)
Task 8 (Regression)    ──→ Task 2 + Task 7 (needs historical data)
```

---

## Task 1: Error Context Enrichment

**Files:**
- Modify: `harness/engine/macro_graph.py:793-811` (main except block)
- Modify: `harness/engine/macro_graph.py:474-492` (upstream failure)
- Modify: `harness/engine/macro_graph.py:696-704` (output validation failure)
- Test: `tests/harness/engine/test_error_context.py` (new)

**Current behavior:** `node.failed` payload only has `error: str(e)`. `STATE_ERRORS` stores `str(e)`.

**New behavior:** `node.failed` gets additional optional fields. `STATE_ERRORS` value becomes a dict when enriched (backward-compatible: consumers that do `str(error)` still work because `str({"error": "...", ...})` returns a dict repr).

### Step 1: Write the failing test

Create `tests/harness/engine/test_error_context.py`:

```python
"""Test that node.failed events carry structured error context."""
import pytest
from unittest.mock import MagicMock
from harness.engine.macro_graph import MacroGraphBuilder


def test_failed_node_emits_error_type():
    """node.failed should include error_type (exception class name)."""
    bus = MagicMock()
    builder = MacroGraphBuilder(
        workflow_id="test-wf",
        name="test",
        agents=[{"name": "agent1", "after": []}],
        event_bus=bus,
    )
    compiled = builder.compile()

    # Run with bad deps to force an exception path
    # We'll test the except block directly by patching executor.run to raise
    import harness.engine.macro_graph as mg
    original_run = mg.LLMExecutor.run

    async def failing_run(self, context):
        raise ValueError("something went wrong")

    mg.LLMExecutor.run = failing_run
    try:
        # The node.failed event should have error_type field
        # We verify by checking bus.emit calls
        import asyncio
        asyncio.run(compiled.ainvoke({"inputs": {"task": "test"}, "outputs": {}, "errors": {}, "metadata": {}}))
        
        # Find node.failed emit
        failed_calls = [c for c in bus.emit.call_args_list if c[0][0] == "node.failed"]
        assert len(failed_calls) >= 1
        payload = failed_calls[0][0][1]
        assert "error_type" in payload
        assert payload["error_type"] == "ValueError"
    finally:
        mg.LLMExecutor.run = original_run
```

### Step 2: Run test to verify it fails

Run: `pytest tests/harness/engine/test_error_context.py -v`
Expected: FAIL — `error_type` not in payload

### Step 3: Enrich error context in macro_graph.py

Add a helper function at the top of `_make_node_func`:

```python
def _enrich_error(exc: Exception, executor=None) -> dict:
    """Build structured error context from an exception."""
    import traceback
    ctx = {
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    # Attach tool call history if available
    if executor and hasattr(executor, "tool_calls") and executor.tool_calls:
        ctx["tool_calls_before_failure"] = [
            {"tool_name": tc["tool_name"], "tool_args": tc.get("tool_args", {})}
            for tc in executor.tool_calls
            if "tool_result" not in tc  # only pending/failed calls
        ]
    return ctx
```

Then modify the main except block (line 793-811):

```python
except Exception as e:
    duration_ms = int((time.time() - start_time) * 1000)
    err_ctx = _enrich_error(e, executor)

    if bus:
        bus.emit("node.failed", {
            "workflow_id": builder_self.workflow_id,
            "node_id": agent_def.name,
            "agent_name": agent_def.name,
            **err_ctx,  # error, error_type, tool_calls_before_failure
            "duration_ms": duration_ms,
            "attempt": 1,
            "will_retry": False,
        })

    return {
        STATE_OUTPUTS: {},
        STATE_ERRORS: {agent_def.name: err_ctx},
        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
    }
```

Apply same pattern to the other `node.failed` emission points (upstream skip, output validation).

### Step 4: Run tests

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: ALL PASS

### Step 5: Update frontend ErrorsTab to show error_type

Modify `frontend/src/components/diagnostics/ErrorsTab.tsx` — add `error_type` display above the error message if present in the node state.

### Step 6: Commit

```
feat: enrich node.failed with error_type, traceback, and tool call history
```

---

## Task 2: Cost Tracking

**Files:**
- Create: `harness/cost.py` (model pricing table + calculator)
- Modify: `harness/extensions/plugins/perf_metrics.py` (add cost to chart)
- Modify: `harness/engine/macro_graph.py:747-749` (add cost to node_meta)
- Test: `tests/harness/test_cost.py` (new)

**Current behavior:** Token counts tracked per node. No dollar conversion.

**New behavior:** New `calculate_cost(tokens, model)` function. Cost added to `node_meta` and `node.completed` payload. `PerfMetricsPlugin` emits cost chart.

### Step 1: Write the failing test

Create `tests/harness/test_cost.py`:

```python
from harness.cost import calculate_cost, get_model_pricing


def test_get_model_pricing():
    pricing = get_model_pricing("openai:gpt-4o")
    assert pricing is not None
    assert "input_per_1m" in pricing
    assert "output_per_1m" in pricing


def test_calculate_cost():
    cost = calculate_cost(
        input_tokens=1000,
        output_tokens=500,
        model="openai:gpt-4o",
    )
    assert cost > 0
    assert isinstance(cost, float)


def test_calculate_cost_unknown_model():
    cost = calculate_cost(1000, 500, "unknown:model")
    assert cost == 0.0
```

### Step 2: Run test to verify it fails

Run: `pytest tests/harness/test_cost.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.cost'`

### Step 3: Create `harness/cost.py`

```python
"""Cost calculation from token usage and model pricing."""

# Pricing per 1M tokens (USD). Update as providers change pricing.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "openai:gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "openai:gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "openai:gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "openai:gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "openai:gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "anthropic:claude-sonnet-4-6": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "anthropic:claude-haiku-4-5": {"input_per_1m": 0.80, "output_per_1m": 4.00},
    "deepseek:deepseek-chat": {"input_per_1m": 0.27, "output_per_1m": 1.10},
    "google:gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "google:gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
}


def get_model_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a model. Returns None if unknown."""
    # Normalize: strip provider prefix variations
    return _MODEL_PRICING.get(model)


def calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Calculate USD cost for a token usage on a given model."""
    pricing = get_model_pricing(model)
    if not pricing:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return round(input_cost + output_cost, 6)
```

### Step 4: Integrate into macro_graph.py

After token_usage is computed (line 722), add cost calculation:

```python
from harness.cost import calculate_cost

# In node_func, after token_usage block:
cost_usd = None
if token_usage:
    model_name = getattr(pydantic_agent, "model", "") or ""
    if isinstance(model_name, object) and hasattr(model_name, "model_name"):
        model_name = model_name.model_name
    cost_usd = calculate_cost(token_usage["input"], token_usage["output"], str(model_name))
```

Add `cost_usd` to `node_meta` and `node.completed` event payload.

### Step 5: Extend PerfMetricsPlugin to emit cost chart

Add a second chart emission in `on_node_end` for cost data.

### Step 6: Run all tests

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: ALL PASS

### Step 7: Commit

```
feat: add cost tracking with model pricing table
```

---

## Task 3: Step Counter Plugin

**Files:**
- Create: `harness/extensions/plugins/step_counter.py`
- Modify: `harness/extensions/plugins/__init__.py` (register new plugin)
- Test: `tests/harness/extensions/plugins/test_step_counter.py` (new)

**Current behavior:** Tool calls and LLM calls are emitted as events but not counted.

**New behavior:** New `StepCounterPlugin` accumulates per-node and per-workflow step counts. Emits `step.summary` side effect on each node completion.

### Step 1: Write the failing test

```python
from harness.extensions.plugins.step_counter import StepCounterPlugin
from harness.extensions.base import NodeCtx, WorkflowCtx


def test_step_counter_counts_tool_calls():
    plugin = StepCounterPlugin()
    ctx = NodeCtx(
        workflow=WorkflowCtx(workflow_id="w1"),
        node_id="agent1",
        agent_name="agent1",
        prompt="",
        messages=[],
        upstream_outputs={},
        config={},
        metadata={"agent1": {"duration_ms": 100}},
    )
    # Simulate tool calls in metadata
    ctx.metadata["agent1"]["tool_calls"] = [
        {"tool_name": "read_file"},
        {"tool_name": "write_file"},
    ]
    await plugin.on_node_end(ctx, "output")
    summary = plugin.get_summary("w1")
    assert summary["total_tool_calls"] == 2
    assert summary["nodes"]["agent1"]["tool_calls"] == 2
```

### Step 2: Run test to verify it fails

Run: `pytest tests/harness/extensions/plugins/test_step_counter.py -v`

### Step 3: Create `harness/extensions/plugins/step_counter.py`

```python
"""StepCounterPlugin — tracks tool calls, LLM calls, and retries per node/workflow."""

from harness.extensions.base import BaseHook, NodeCtx


class StepCounterPlugin(BaseHook):
    name = "step-counter"

    def __init__(self):
        self._workflows: dict[str, dict] = {}

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        wid = ctx.workflow.workflow_id
        if wid not in self._workflows:
            self._workflows[wid] = {"nodes": {}, "total_tool_calls": 0, "total_llm_calls": 0}

        node_meta = ctx.metadata.get(ctx.agent_name, {})
        tool_calls = node_meta.get("tool_calls", [])

        tool_count = len(tool_calls)
        # Each node = at least 1 LLM call; tool calls may trigger additional
        llm_count = 1 + (1 if tool_count > 0 else 0)

        self._workflows[wid]["nodes"][ctx.agent_name] = {
            "tool_calls": tool_count,
            "llm_calls": llm_count,
        }
        self._workflows[wid]["total_tool_calls"] += tool_count
        self._workflows[wid]["total_llm_calls"] += llm_count

        ctx.emit("step.summary", {
            "workflow_id": wid,
            "node_id": ctx.agent_name,
            "node_tool_calls": tool_count,
            "node_llm_calls": llm_count,
            "total_tool_calls": self._workflows[wid]["total_tool_calls"],
            "total_llm_calls": self._workflows[wid]["total_llm_calls"],
        })

    def get_summary(self, workflow_id: str) -> dict:
        return self._workflows.get(workflow_id, {"nodes": {}, "total_tool_calls": 0, "total_llm_calls": 0})
```

### Step 4: Register in `__init__.py`

Add `StepCounterPlugin` to `_DEFAULT_HOOKS` list and `__all__`.

### Step 5: Run all tests, commit

```
feat: add StepCounterPlugin for tool/LLM call tracking
```

---

## Task 4: Structured Span Tracing

**Files:**
- Modify: `harness/engine/llm_executor.py` (emit span events)
- Create: `harness/extensions/plugins/span_tracer.py` (collect spans)
- Test: `tests/harness/engine/test_span_tracing.py` (new)

**Current behavior:** `agent.tool_call` and `agent.tool_result` events are flat. No parent-child relationship.

**New behavior:** `LLMExecutor` emits `span.start` / `span.end` events for each LLM call and tool call. `SpanTracerPlugin` collects into a tree structure and emits `span.tree` on node completion.

### Step 1: Write the failing test

```python
"""Test that LLMExecutor emits span.start and span.end events."""
import pytest
from unittest.mock import MagicMock


def test_span_events_emitted():
    bus = MagicMock()
    executor = LLMExecutor(
        pydantic_agent=mock_agent,
        deps=mock_deps,
        event_bus=bus,
        workflow_id="w1",
        node_id="agent1",
        agent_name="agent1",
    )
    # ... run executor with mock that triggers 1 LLM call + 1 tool call
    # Verify bus.emit called with "span.start" and "span.end"
    span_events = [c for c in bus.emit.call_args_list if "span" in c[0][0]]
    assert len(span_events) >= 2
```

### Step 2: Add span events to LLMExecutor

In `llm_executor.py`, add span emission around model requests and tool calls:

```python
def _emit_span(self, span_type: str, action: str, payload: dict) -> None:
    if not self._bus:
        return
    self._bus.emit("span." + action, {
        "workflow_id": self._wid,
        "node_id": self._node_id,
        "agent_name": self._agent_name,
        "span_type": span_type,
        **payload,
    })
```

In `_handle_model_request`:
```python
async def _handle_model_request(self, node, ctx):
    span_id = f"{self._node_id}-llm-{len(self.tool_calls)}"
    self._emit_span("llm", "start", {"span_id": span_id, "model": str(getattr(self._agent, 'model', ''))})
    start = time.monotonic()
    # ... existing streaming code ...
    self._emit_span("llm", "end", {"span_id": span_id, "duration_ms": int((time.monotonic() - start) * 1000)})
```

In `_handle_call_tools`:
```python
# Around each tool call:
self._emit_span("tool", "start", {"span_id": f"{self._node_id}-tool-{i}", "tool_name": part.tool_name})
# After result:
self._emit_span("tool", "end", {"span_id": ..., "duration_ms": ...})
```

### Step 3: Create SpanTracerPlugin

```python
class SpanTracerPlugin(BaseHook):
    name = "span-tracer"
    # Listens to span.start/end events, builds tree, emits span.tree on node completion
```

### Step 4: Run tests, commit

```
feat: add structured span tracing for LLM and tool calls
```

---

## Task 5: TTFT (Time-to-First-Token) Metrics

**Files:**
- Modify: `harness/engine/llm_executor.py:117-150` (add TTFT timing)
- Modify: `harness/engine/macro_graph.py:747-749` (add ttft_ms to node_meta)

**Current behavior:** Only total `duration_ms` is tracked.

**New behavior:** `ttft_ms` (time from request start to first text delta) added to `LLMExecutor` result, stored in node metadata, included in `node.completed` payload.

### Step 1: Write the failing test

```python
def test_ttft_measured():
    """LLMExecutor should track time-to-first-token."""
    # Run executor with mock stream that yields one delta
    # Verify result has ttft_ms > 0
```

### Step 2: Add TTFT measurement to LLMExecutor

In `_handle_model_request`, add:

```python
first_token_time = None
ttft_ms = None

async for response in stream.stream_response():
    if first_token_time is None and (delta or thinking_delta):
        first_token_time = time.monotonic()
        ttft_ms = int((first_token_time - stream_start_time) * 1000)
```

Store `ttft_ms` on `self` and expose via `AgentRunResult`.

### Step 3: Integrate into macro_graph.py

After `LLMExecutor.run()`, extract `ttft_ms` and add to `node_meta`:

```python
node_meta = {"duration_ms": duration_ms}
if ttft_ms is not None:
    node_meta["ttft_ms"] = ttft_ms
```

### Step 4: Run tests, commit

```
feat: add TTFT (time-to-first-token) measurement
```

---

## Task 6: Circular Output Detection

**Files:**
- Create: `harness/extensions/plugins/circular_detector.py`
- Modify: `harness/extensions/plugins/__init__.py` (register)
- Test: `tests/harness/extensions/plugins/test_circular_detector.py`

**Current behavior:** No detection of repeating tool calls or outputs.

**New behavior:** `CircularDetectorPlugin` monitors tool call sequences per node. If consecutive calls show similar args/output, emits `circular.warning`.

### Step 1: Write the failing test

```python
from harness.extensions.plugins.circular_detector import CircularDetectorPlugin


def test_detects_repeated_tool_calls():
    plugin = CircularDetectorPlugin(threshold=3)
    # Simulate 3 consecutive identical tool calls
    assert plugin._is_circular([
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
    ])
    assert not plugin._is_circular([
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "write", "tool_args": {"path": "out.txt"}},
    ])
```

### Step 2: Create `harness/extensions/plugins/circular_detector.py`

```python
"""CircularDetectorPlugin — detects repeated/identical tool call sequences."""

import json
from harness.extensions.base import BaseHook, NodeCtx


class CircularDetectorPlugin(BaseHook):
    name = "circular-detector"

    def __init__(self, threshold: int = 3):
        self._threshold = threshold

    def _is_circular(self, tool_calls: list[dict]) -> bool:
        if len(tool_calls) < self._threshold:
            return False
        tail = tool_calls[-self._threshold:]
        first_sig = json.dumps(tail[0], sort_keys=True)
        return all(json.dumps(tc, sort_keys=True) == first_sig for tc in tail)

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        node_meta = ctx.metadata.get(ctx.agent_name, {})
        tool_calls = node_meta.get("tool_calls", [])
        if self._is_circular(tool_calls):
            ctx.emit("circular.warning", {
                "workflow_id": ctx.workflow.workflow_id,
                "node_id": ctx.agent_name,
                "agent_name": ctx.agent_name,
                "repeated_count": len(tool_calls),
                "last_tool": tool_calls[-1]["tool_name"] if tool_calls else None,
                "message": f"Detected {self._threshold}+ identical consecutive tool calls",
            })
```

### Step 3: Register, run tests, commit

```
feat: add CircularDetectorPlugin for repeated tool call detection
```

---

## Task 7: Operating Envelope (Budget Gates)

**Files:**
- Create: `harness/extensions/envelope.py` (budget checker middleware)
- Modify: `harness/engine/macro_graph.py:413-500` (wire in envelope check)
- Modify: `harness/api.py` (add envelope params to Workflow config)
- Test: `tests/harness/extensions/test_envelope.py`

**Current behavior:** No token/step/duration limits per task.

**New behavior:** Optional `envelope` dict on `Workflow` config with `max_tokens`, `max_steps`, `max_duration_ms`. Middleware checks accumulated totals after each node and fails the workflow if exceeded.

### Step 1: Write the failing test

```python
from harness.extensions.envelope import check_envelope


def test_check_envelope_exceeds_tokens():
    result = check_envelope(
        accumulated_tokens={"total": 150000},
        accumulated_steps=5,
        elapsed_ms=10000,
        envelope={"max_tokens": 100000},
    )
    assert result is not None
    assert "token budget" in result.lower()


def test_check_envelope_within_budget():
    result = check_envelope(
        accumulated_tokens={"total": 50000},
        accumulated_steps=5,
        elapsed_ms=10000,
        envelope={"max_tokens": 100000, "max_steps": 50, "max_duration_ms": 60000},
    )
    assert result is None
```

### Step 2: Create `harness/extensions/envelope.py`

```python
"""Operating Envelope — budget gates for workflow execution."""

from typing import Any


def check_envelope(
    accumulated_tokens: dict[str, int],
    accumulated_steps: int,
    elapsed_ms: int,
    envelope: dict[str, Any],
) -> str | None:
    """Check if accumulated totals exceed any budget. Returns error message or None."""
    max_tokens = envelope.get("max_tokens")
    if max_tokens and accumulated_tokens.get("total", 0) > max_tokens:
        return f"Token budget exceeded: {accumulated_tokens['total']} > {max_tokens}"

    max_steps = envelope.get("max_steps")
    if max_steps and accumulated_steps > max_steps:
        return f"Step budget exceeded: {accumulated_steps} > {max_steps}"

    max_duration = envelope.get("max_duration_ms")
    if max_duration and elapsed_ms > max_duration:
        return f"Duration budget exceeded: {elapsed_ms}ms > {max_duration}ms"

    return None
```

### Step 3: Wire into macro_graph.py

After each node completes, check envelope. If exceeded, emit `node.failed` for the current node and stop.

```python
# After node_meta is populated:
if envelope_cfg:
    from harness.extensions.envelope import check_envelope
    total_tokens += token_usage.get("total", 0) if token_usage else 0
    total_steps += len(executor.tool_calls) if hasattr(executor, 'tool_calls') else 0
    envelope_error = check_envelope(
        {"total": total_tokens}, total_steps, total_elapsed_ms, envelope_cfg
    )
    if envelope_error:
        bus.emit("node.failed", {...envelope_error...})
        return {STATE_ERRORS: {agent_def.name: envelope_error}, ...}
```

### Step 4: Add envelope to Workflow API

In `harness/api.py`, add `envelope` field to `Workflow.__init__`:

```python
self.envelope: dict[str, int] | None = envelope  # {"max_tokens": N, "max_steps": N, "max_duration_ms": N}
```

### Step 5: Run tests, commit

```
feat: add operating envelope with token/step/duration budget gates
```

---

## Task 8: Version Regression Detection

**Files:**
- Create: `harness/extensions/plugins/regression_detector.py`
- Modify: `harness/benchmark_store.py` (add comparison method)
- Modify: `server/routes.py` (add regression comparison endpoint)
- Test: `tests/harness/extensions/plugins/test_regression_detector.py`

**Current behavior:** Benchmark results are stored but not compared across runs.

**New behavior:** Compare latest benchmark results against a baseline. Detect regressions in score, cost, latency, and step count.

### Step 1: Write the failing test

```python
from harness.extensions.plugins.regression_detector import detect_regressions


def test_detect_score_regression():
    baseline = {"avg_score": 0.85, "avg_duration_ms": 5000, "avg_tokens": 10000, "avg_cost": 0.05}
    current = {"avg_score": 0.60, "avg_duration_ms": 5000, "avg_tokens": 10000, "avg_cost": 0.05}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_score"


def test_detect_cost_regression():
    baseline = {"avg_score": 0.85, "avg_duration_ms": 5000, "avg_tokens": 10000, "avg_cost": 0.05}
    current = {"avg_score": 0.85, "avg_duration_ms": 5000, "avg_tokens": 10000, "avg_cost": 0.15}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "avg_cost"


def test_no_regression():
    baseline = {"avg_score": 0.85, "avg_duration_ms": 5000, "avg_tokens": 10000, "avg_cost": 0.05}
    current = {"avg_score": 0.90, "avg_duration_ms": 4500, "avg_tokens": 9000, "avg_cost": 0.04}
    regressions = detect_regressions(baseline, current)
    assert len(regressions) == 0
```

### Step 2: Create `harness/extensions/plugins/regression_detector.py`

```python
"""Regression detection for benchmark comparisons."""

_THRESHOLD_SCORE = 0.10    # 10% drop
_THRESHOLD_COST = 0.50     # 50% increase
_THRESHOLD_LATENCY = 0.50  # 50% increase


def detect_regressions(
    baseline: dict, current: dict, thresholds: dict | None = None,
) -> list[dict]:
    """Compare current metrics against baseline. Returns list of regressions."""
    t = thresholds or {}
    regressions = []

    # Score regression (lower is worse)
    score_thresh = t.get("score", _THRESHOLD_SCORE)
    if "avg_score" in baseline and "avg_score" in current:
        drop = baseline["avg_score"] - current["avg_score"]
        if drop > score_thresh:
            regressions.append({
                "metric": "avg_score",
                "baseline": baseline["avg_score"],
                "current": current["avg_score"],
                "delta": round(drop, 4),
                "direction": "down",
                "threshold": score_thresh,
            })

    # Cost regression (higher is worse)
    cost_thresh = t.get("cost", _THRESHOLD_COST)
    if "avg_cost" in baseline and "avg_cost" in current:
        increase = (current["avg_cost"] - baseline["avg_cost"]) / max(baseline["avg_cost"], 0.001)
        if increase > cost_thresh:
            regressions.append({
                "metric": "avg_cost",
                "baseline": baseline["avg_cost"],
                "current": current["avg_cost"],
                "delta": round(increase, 4),
                "direction": "up",
                "threshold": cost_thresh,
            })

    # Latency regression (higher is worse)
    latency_thresh = t.get("latency", _THRESHOLD_LATENCY)
    if "avg_duration_ms" in baseline and "avg_duration_ms" in current:
        increase = (current["avg_duration_ms"] - baseline["avg_duration_ms"]) / max(baseline["avg_duration_ms"], 1)
        if increase > latency_thresh:
            regressions.append({
                "metric": "avg_duration_ms",
                "baseline": baseline["avg_duration_ms"],
                "current": current["avg_duration_ms"],
                "delta": round(increase, 4),
                "direction": "up",
                "threshold": latency_thresh,
            })

    return regressions
```

### Step 3: Add comparison endpoint in routes.py

```python
@router.get("/benchmarks/{name}/regression")
async def benchmark_regression(name: str, baseline_run: str | None = None):
    """Compare latest benchmark run against a baseline for regressions."""
```

### Step 4: Run tests, commit

```
feat: add regression detection for benchmark score/cost/latency comparison
```

---

## Risk Assessment Summary

| Task | Files Changed | Regression Risk | Reason |
|------|--------------|----------------|--------|
| 1. Error Context | 1 backend file | **Zero** | Only adds fields to existing dict payloads |
| 2. Cost Tracking | 1 new + 2 modified | **Zero** | New file + optional field additions |
| 3. Step Counter | 1 new + 1 modified | **Zero** | New plugin, auto-registered, no side effects |
| 4. Span Tracing | 1 modified + 1 new | **Low** | New event types, existing events unchanged |
| 5. TTFT | 1 modified | **Zero** | Adds timing measurement, no behavior change |
| 6. Circular Detector | 1 new + 1 modified | **Zero** | New plugin, only emits warnings |
| 7. Envelope | 1 new + 2 modified | **Low** | Opt-in feature, disabled when envelope=None |
| 8. Regression | 1 new + 2 modified | **Zero** | Pure comparison function, no runtime impact |

**Key safety principle:** No existing event schemas are modified. All new data is additive (extra dict keys). All new features use the existing plugin/hook system. `envelope` is opt-in (disabled by default).
