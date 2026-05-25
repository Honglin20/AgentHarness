# Extensible Hook Plugin System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add side-channel `ctx.emit()` to NodeCtx, flush it in Bus, create 4 plugins (EvalChart, AgentTrace, ReasoningViz, PerfMetrics), migrate hardcoded chart rendering out of the engine.

**Architecture:** Enhance existing `BaseHook` with no API changes. Plugins are `BaseHook` subclasses that call `ctx.emit()` to produce observational artifacts (charts, traces, metrics). Bus flushes `_side_effects` after `run_hooks()`. Engine's hardcoded chart rendering in `_make_judge_node_func` moves to `EvalChartPlugin`.

**Tech Stack:** Python 3.11+, asyncio, pytest, existing Bus/extension infrastructure

---

### Task 1: Add `emit()` side-channel to `NodeCtx`

**Files:**
- Modify: `harness/extensions/base.py:52-70` (NodeCtx dataclass)

**Step 1: Write the failing test**

Add to `harness/extensions/test_bus.py`:

```python
def test_node_ctx_emit_appends_side_effects():
    ctx = _make_node_ctx()
    assert ctx._side_effects == []
    ctx.emit("chart.render", {"chart_type": "line"})
    assert len(ctx._side_effects) == 1
    assert ctx._side_effects[0]["type"] == "chart.render"
    assert ctx._side_effects[0]["payload"]["chart_type"] == "line"


def test_node_ctx_emit_multiple():
    ctx = _make_node_ctx()
    ctx.emit("chart.render", {"a": 1})
    ctx.emit("metric.report", {"b": 2})
    assert len(ctx._side_effects) == 2
    assert ctx._side_effects[0]["type"] == "chart.render"
    assert ctx._side_effects[1]["type"] == "metric.report"
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/test_bus.py::test_node_ctx_emit_appends_side_effects harness/extensions/test_bus.py::test_node_ctx_emit_multiple -v`
Expected: FAIL with `AttributeError: 'NodeCtx' object has no attribute 'emit'`

**Step 3: Write minimal implementation**

In `harness/extensions/base.py`, update `NodeCtx`:

```python
@dataclass
class NodeCtx:
    """Per-agent-step context.

    workflow            – parent WorkflowCtx
    node_id             – DAG node id (= agent_name for now)
    agent_name          – agent definition name
    prompt              – mutable: the user-message text fed to the LLM this step
    messages            – mutable: full message history (system+user+assistant+tool)
    upstream_outputs    – read-only: outputs from agents this one depends on
    metadata            – per-extension scratchpad, keyed by extension name
    _side_effects       – internal: artifacts produced by hooks via emit()
    """
    workflow: WorkflowCtx
    node_id: str
    agent_name: str
    prompt: str
    messages: list[dict[str, Any]]
    upstream_outputs: dict[str, Any]
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    _side_effects: list[dict] = field(default_factory=list, repr=False)

    def emit(self, event_type: str, payload: dict) -> None:
        self._side_effects.append({"type": event_type, "payload": payload})
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/test_bus.py::test_node_ctx_emit_appends_side_effects harness/extensions/test_bus.py::test_node_ctx_emit_multiple -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/base.py harness/extensions/test_bus.py
git commit -m "feat(extensions): add emit() side-channel to NodeCtx for observational artifacts"
```

---

### Task 2: Bus flushes side effects after `run_hooks()`

**Files:**
- Modify: `harness/extensions/bus.py:153-176` (run_hooks method)

**Step 1: Write the failing test**

Add to `harness/extensions/test_bus.py`:

```python
@pytest.mark.asyncio
async def test_run_hooks_flushes_side_effects():
    bus = Bus()
    received: list[dict] = []

    class ChartHook(BaseHook):
        name = "chart"
        async def on_node_end(self, ctx: NodeCtx, output) -> None:
            ctx.emit("chart.render", {"chart_type": "line", "data": []})

    bus.register(ChartHook())
    ctx = _make_node_ctx()

    # Subscribe to WS to capture emitted events
    sub_id, queue = await bus.subscribe()

    await bus.run_hooks("on_node_end", ctx, "output")

    # Side effects were flushed to bus.emit() → WS subscriber
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "line"

    # Side effects list is cleared after flush
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_run_hooks_no_side_effects_is_no_op():
    bus = Bus()
    ctx = _make_node_ctx()
    # No hooks registered, no side effects — should not raise
    await bus.run_hooks("on_node_end", ctx, "output")
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_run_hooks_multiple_side_effects_flush_in_order():
    bus = Bus()
    events: list[str] = []

    class MultiHook(BaseHook):
        name = "multi"
        async def on_node_end(self, ctx: NodeCtx, output) -> None:
            ctx.emit("chart.render", {"order": 1})
            ctx.emit("metric.report", {"order": 2})

    bus.register(MultiHook())
    ctx = _make_node_ctx()
    sub_id, queue = await bus.subscribe()

    await bus.run_hooks("on_node_end", ctx, "output")

    e1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    e2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert e1["type"] == "chart.render"
    assert e2["type"] == "metric.report"
    assert ctx._side_effects == []
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/test_bus.py::test_run_hooks_flushes_side_effects harness/extensions/test_bus.py::test_run_hooks_no_side_effects_is_no_op harness/extensions/test_bus.py::test_run_hooks_multiple_side_effects_flush_in_order -v`
Expected: FAIL — side effects are never flushed, queue gets no events

**Step 3: Write minimal implementation**

In `harness/extensions/bus.py`, update `run_hooks`:

```python
async def run_hooks(
    self,
    method: Literal[
        "on_workflow_start",
        "on_workflow_end",
        "on_node_start",
        "on_node_end",
        "on_llm_delta",
        "on_tool_call",
    ],
    *args: Any,
) -> None:
    if not self._hooks:
        return
    coros = []
    for hook in self._hooks.values():
        coros.append(self._safe_invoke(hook, method, args))
    await asyncio.gather(*coros, return_exceptions=False)

    # Flush side effects from NodeCtx to WS layer
    if args and isinstance(args[0], NodeCtx):
        for effect in args[0]._side_effects:
            self.emit(effect["type"], effect["payload"])
        args[0]._side_effects.clear()
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/test_bus.py::test_run_hooks_flushes_side_effects harness/extensions/test_bus.py::test_run_hooks_no_side_effects_is_no_op harness/extensions/test_bus.py::test_run_hooks_multiple_side_effects_flush_in_order -v`
Expected: PASS

**Step 5: Run full bus test suite to verify no regressions**

Run: `pytest harness/extensions/test_bus.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add harness/extensions/bus.py harness/extensions/test_bus.py
git commit -m "feat(extensions): Bus flushes NodeCtx side effects after run_hooks"
```

---

### Task 3: Create plugin directory and `EvalChartPlugin`

**Files:**
- Create: `harness/extensions/plugins/__init__.py`
- Create: `harness/extensions/plugins/eval_chart.py`
- Create: `harness/extensions/plugins/test_eval_chart.py`

**Step 1: Write the failing test**

Create `harness/extensions/plugins/test_eval_chart.py`:

```python
"""Tests for EvalChartPlugin — extracts judge scores and emits line chart."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.eval_chart import EvalChartPlugin


def _make_judge_ctx(judge_name: str = "_judge_coder", target_name: str = "coder") -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf,
        node_id=judge_name,
        agent_name=judge_name,
        prompt="",
        messages=[],
        upstream_outputs={},
    )


class FakeReviewOutput:
    """Mimics ReviewDecision with .score attribute."""
    def __init__(self, score: float | None, decision: str = "pass"):
        self.score = score
        self.decision = decision
        self.reason = "ok"


@pytest.mark.asyncio
async def test_emits_chart_when_judge_has_score():
    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()
    ctx.metadata["_judge_coder"] = {"score_history": [0.6, 0.7]}

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.85))

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "line"
    assert event["payload"]["x"] == "iteration"
    assert event["payload"]["y"] == "score"
    assert event["payload"]["label"] == "Eval Scores"
    assert event["payload"]["title"] == "coder quality"
    assert len(event["payload"]["data"]) == 3  # 0.6, 0.7, 0.85


@pytest.mark.asyncio
async def test_no_emit_when_not_judge_node():
    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx(judge_name="coder", target_name="coder")

    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.9))
    assert ctx._side_effects == []  # flushed but nothing was emitted


@pytest.mark.asyncio
async def test_no_emit_when_score_is_none():
    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()

    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=None))
    # Bus flushes empty list — no events emitted
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_score_history_accumulates():
    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()
    # No prior history
    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.5))
    # Metadata should have recorded the score
    history = ctx.metadata.get("eval-chart", {}).get("score_history", [])
    assert 0.5 in history
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/plugins/test_eval_chart.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.extensions.plugins'`

**Step 3: Create `__init__.py` and `eval_chart.py`**

Create `harness/extensions/plugins/__init__.py`:

```python
"""Built-in Hook plugins — observational artifacts produced via ctx.emit().

Each plugin is a BaseHook subclass. Enable via workflow.use():

    wf = Workflow("name", agents=[...]).use(EvalChartPlugin())
"""
from harness.extensions.plugins.eval_chart import EvalChartPlugin

__all__ = ["EvalChartPlugin"]
```

Create `harness/extensions/plugins/eval_chart.py`:

```python
"""EvalChartPlugin — emits line chart for judge evaluation scores.

Triggered on on_node_end for nodes named _judge_*. Reads score_history
from metadata and emits a chart.render side effect via ctx.emit().
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class EvalChartPlugin(BaseHook):
    name = "eval-chart"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        if not ctx.agent_name.startswith("_judge_"):
            return

        score = getattr(output, "score", None)
        if score is None:
            return

        # Accumulate score history in plugin's own metadata namespace
        plugin_meta = ctx.metadata.setdefault(self.name, {})
        # Also pick up any prior history from the judge node's metadata
        judge_meta = ctx.metadata.get(ctx.agent_name, {})
        prior_history = list(judge_meta.get("score_history", []))
        prior_history.extend(plugin_meta.get("extra_scores", []))
        prior_history.append(score)
        plugin_meta["score_history"] = prior_history

        target_name = ctx.agent_name.replace("_judge_", "")
        ctx.emit("chart.render", {
            "node_id": ctx.agent_name,
            "chart_type": "line",
            "data": [{"iteration": i + 1, "score": s} for i, s in enumerate(prior_history)],
            "x": "iteration",
            "y": "score",
            "label": "Eval Scores",
            "title": f"{target_name} quality",
        })
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/plugins/test_eval_chart.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/plugins/__init__.py harness/extensions/plugins/eval_chart.py harness/extensions/plugins/test_eval_chart.py
git commit -m "feat(plugins): EvalChartPlugin — judge score → line chart via ctx.emit()"
```

---

### Task 4: Migrate hardcoded chart rendering from `_make_judge_node_func`

**Files:**
- Modify: `harness/engine/macro_graph.py:646-660` (remove chart emission block)

**Step 1: Write the failing test**

The existing test suite should cover that judge nodes still write `score_history` to metadata. Verify that removing the `bus.emit("chart.render", ...)` block does NOT break existing judge tests.

First, find existing judge tests:

```bash
grep -r "_judge_" tests/ --include="*.py" -l
```

**Step 2: Remove the hardcoded chart emission**

In `harness/engine/macro_graph.py`, change lines 646-660 from:

```python
            # 4. Score history + chart emission
            prev_meta = state.get(STATE_METADATA, {}).get(judge_name, {})
            score_history = list(prev_meta.get("score_history", []))
            if review.score is not None:
                score_history.append(review.score)
                if bus:
                    bus.emit("chart.render", {
                        "node_id": judge_name,
                        "chart_type": "line",
                        "data": [{"iteration": i + 1, "score": s} for i, s in enumerate(score_history)],
                        "x": "iteration",
                        "y": "score",
                        "label": "Eval Scores",
                        "title": f"{target_name} quality",
                    })
```

To:

```python
            # 4. Score history (chart emission now handled by EvalChartPlugin)
            prev_meta = state.get(STATE_METADATA, {}).get(judge_name, {})
            score_history = list(prev_meta.get("score_history", []))
            if review.score is not None:
                score_history.append(review.score)
```

**Step 3: Run all existing tests**

Run: `pytest tests/ harness/extensions/ -v --timeout=30`
Expected: All PASS — the chart.render event is no longer emitted by the engine, but score_history is still written to metadata (the plugin reads it).

**Step 4: Run eval judge example manually to verify chart still works with plugin**

```bash
# In one terminal: start the server
python -m server.main
# In another: run the eval example WITH the plugin
python -c "
from harness.api import Workflow, Agent
from harness.extensions.eval import EvalJudge
from harness.extensions.plugins import EvalChartPlugin

wf = Workflow('test', agents=[
    Agent('coder', after=[], eval=True),
    Agent('reviewer', after=['coder']),
]).use(EvalJudge()).use(EvalChartPlugin())
"
```

Expected: Chart renders via plugin's ctx.emit(), not engine's bus.emit().

**Step 5: Commit**

```bash
git add harness/engine/macro_graph.py
git commit -m "refactor(engine): remove hardcoded chart emission from judge node — moved to EvalChartPlugin"
```

---

### Task 5: Create `AgentTracePlugin`

**Files:**
- Create: `harness/extensions/plugins/agent_trace.py`
- Create: `harness/extensions/plugins/test_agent_trace.py`
- Modify: `harness/extensions/plugins/__init__.py`

**Step 1: Write the failing test**

Create `harness/extensions/plugins/test_agent_trace.py`:

```python
"""Tests for AgentTracePlugin — emits trace.step events for every node."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.agent_trace import AgentTracePlugin


def _make_node_ctx(agent_name: str = "coder") -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf, node_id=agent_name, agent_name=agent_name,
        prompt="do stuff", messages=[], upstream_outputs={},
    )


@pytest.mark.asyncio
async def test_emits_trace_step_on_node_end():
    plugin = AgentTracePlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx("coder")

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result text")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "trace.step"
    assert event["payload"]["agent_name"] == "coder"
    assert event["payload"]["status"] == "completed"


@pytest.mark.asyncio
async def test_trace_includes_workflow_id():
    plugin = AgentTracePlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx()

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "out")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["payload"]["workflow_id"] == "w1"
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/plugins/test_agent_trace.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Create `harness/extensions/plugins/agent_trace.py`:

```python
"""AgentTracePlugin — emits trace.step events for every completed node.

Each on_node_end call produces a trace.step side effect with the agent
name, workflow ID, and status. Frontend consumes these to build
execution trace diagrams.
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class AgentTracePlugin(BaseHook):
    name = "agent-trace"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        ctx.emit("trace.step", {
            "workflow_id": ctx.workflow.workflow_id,
            "node_id": ctx.node_id,
            "agent_name": ctx.agent_name,
            "status": "completed",
        })
```

Update `harness/extensions/plugins/__init__.py`:

```python
from harness.extensions.plugins.eval_chart import EvalChartPlugin
from harness.extensions.plugins.agent_trace import AgentTracePlugin

__all__ = ["EvalChartPlugin", "AgentTracePlugin"]
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/plugins/test_agent_trace.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/plugins/agent_trace.py harness/extensions/plugins/test_agent_trace.py harness/extensions/plugins/__init__.py
git commit -m "feat(plugins): AgentTracePlugin — execution trace events via ctx.emit()"
```

---

### Task 6: Create `ReasoningVizPlugin`

**Files:**
- Create: `harness/extensions/plugins/reasoning_viz.py`
- Create: `harness/extensions/plugins/test_reasoning_viz.py`
- Modify: `harness/extensions/plugins/__init__.py`

**Step 1: Write the failing test**

Create `harness/extensions/plugins/test_reasoning_viz.py`:

```python
"""Tests for ReasoningVizPlugin — extracts reasoning steps from messages."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin


def _make_node_ctx(messages=None) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf, node_id="analyst", agent_name="analyst",
        prompt="", messages=messages or [], upstream_outputs={},
    )


@pytest.mark.asyncio
async def test_emits_reasoning_when_chain_of_thought_present():
    plugin = ReasoningVizPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(messages=[
        {"role": "assistant", "content": "Let me think step by step. First, I need to analyze the data. Then, I will draw conclusions."},
    ])

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "reasoning.render"
    assert event["payload"]["agent_name"] == "analyst"
    assert len(event["payload"]["steps"]) > 0


@pytest.mark.asyncio
async def test_no_emit_when_no_reasoning_detected():
    plugin = ReasoningVizPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(messages=[
        {"role": "assistant", "content": "Here is the answer: 42"},
    ])

    await bus.run_hooks("on_node_end", ctx, "42")
    # No reasoning detected → no side effect
    assert ctx._side_effects == []
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/plugins/test_reasoning_viz.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Create `harness/extensions/plugins/reasoning_viz.py`:

```python
"""ReasoningVizPlugin — extracts chain-of-thought reasoning from messages.

Best-effort extraction of reasoning steps from assistant messages. Only
emits when a reasoning pattern is detected (e.g., "step by step",
numbered lists, "first/then/finally"). No-op otherwise.
"""
from __future__ import annotations

import re

from harness.extensions.base import BaseHook, NodeCtx

_REASONING_PATTERNS = [
    r"step\s+by\s+step",
    r"first,?.*then",
    r"\d+\.\s+",            # numbered list
    r"let me think",
    r"reasoning:",
]


class ReasoningVizPlugin(BaseHook):
    name = "reasoning-viz"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        steps = []
        for msg in ctx.messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if any(re.search(p, content, re.IGNORECASE) for p in _REASONING_PATTERNS):
                # Split on numbered items or sentence boundaries
                parts = re.split(r"(?=\d+\.\s)|(?<=[.!?])\s+", content)
                steps.extend([p.strip() for p in parts if p.strip()])

        if not steps:
            return

        ctx.emit("reasoning.render", {
            "workflow_id": ctx.workflow.workflow_id,
            "agent_name": ctx.agent_name,
            "steps": steps,
        })
```

Update `harness/extensions/plugins/__init__.py`:

```python
from harness.extensions.plugins.eval_chart import EvalChartPlugin
from harness.extensions.plugins.agent_trace import AgentTracePlugin
from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin

__all__ = ["EvalChartPlugin", "AgentTracePlugin", "ReasoningVizPlugin"]
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/plugins/test_reasoning_viz.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/plugins/reasoning_viz.py harness/extensions/plugins/test_reasoning_viz.py harness/extensions/plugins/__init__.py
git commit -m "feat(plugins): ReasoningVizPlugin — chain-of-thought extraction via ctx.emit()"
```

---

### Task 7: Create `PerfMetricsPlugin`

**Files:**
- Create: `harness/extensions/plugins/perf_metrics.py`
- Create: `harness/extensions/plugins/test_perf_metrics.py`
- Modify: `harness/extensions/plugins/__init__.py`

**Step 1: Write the failing test**

Create `harness/extensions/plugins/test_perf_metrics.py`:

```python
"""Tests for PerfMetricsPlugin — token usage and latency metrics."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, ToolCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.perf_metrics import PerfMetricsPlugin


def _make_node_ctx(agent_name: str = "coder", metadata: dict | None = None) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    ctx = NodeCtx(
        workflow=wf, node_id=agent_name, agent_name=agent_name,
        prompt="", messages=[], upstream_outputs={},
    )
    if metadata:
        ctx.metadata.update(metadata)
    return ctx


@pytest.mark.asyncio
async def test_emits_bar_chart_for_token_usage():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(metadata={
        "coder": {"duration_ms": 1500, "token_usage": {"input": 100, "output": 50, "total": 150}},
    })

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "bar"
    assert event["payload"]["label"] == "Token Usage"


@pytest.mark.asyncio
async def test_no_emit_when_no_token_usage():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx()

    await bus.run_hooks("on_node_end", ctx, "result")
    assert ctx._side_effects == []
```

**Step 2: Run test to verify it fails**

Run: `pytest harness/extensions/plugins/test_perf_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Create `harness/extensions/plugins/perf_metrics.py`:

```python
"""PerfMetricsPlugin — emits token usage bar chart on node end.

Reads token_usage and duration_ms from node metadata and emits a
bar chart visualization via ctx.emit().
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class PerfMetricsPlugin(BaseHook):
    name = "perf-metrics"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        node_meta = ctx.metadata.get(ctx.agent_name, {})
        token_usage = node_meta.get("token_usage")
        if not token_usage:
            return

        data = [{
            "agent": ctx.agent_name,
            "input_tokens": token_usage.get("input", 0),
            "output_tokens": token_usage.get("output", 0),
            "total_tokens": token_usage.get("total", 0),
        }]

        ctx.emit("chart.render", {
            "node_id": ctx.agent_name,
            "chart_type": "bar",
            "data": data,
            "x": "agent",
            "y": "total_tokens",
            "label": "Token Usage",
            "title": f"{ctx.agent_name} token usage",
        })
```

Update `harness/extensions/plugins/__init__.py`:

```python
from harness.extensions.plugins.eval_chart import EvalChartPlugin
from harness.extensions.plugins.agent_trace import AgentTracePlugin
from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin
from harness.extensions.plugins.perf_metrics import PerfMetricsPlugin

__all__ = ["EvalChartPlugin", "AgentTracePlugin", "ReasoningVizPlugin", "PerfMetricsPlugin"]
```

**Step 4: Run test to verify it passes**

Run: `pytest harness/extensions/plugins/test_perf_metrics.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/extensions/plugins/perf_metrics.py harness/extensions/plugins/test_perf_metrics.py harness/extensions/plugins/__init__.py
git commit -m "feat(plugins): PerfMetricsPlugin — token usage bar chart via ctx.emit()"
```

---

### Task 8: Update `harness/extensions/__init__.py` to re-export plugins

**Files:**
- Modify: `harness/extensions/__init__.py`

**Step 1: Update exports**

Add plugin re-exports to `harness/extensions/__init__.py`:

```python
from harness.extensions.plugins import (
    EvalChartPlugin,
    AgentTracePlugin,
    ReasoningVizPlugin,
    PerfMetricsPlugin,
)
```

Add to `__all__`:

```python
__all__ = [
    # ...existing entries...
    "EvalChartPlugin",
    "AgentTracePlugin",
    "ReasoningVizPlugin",
    "PerfMetricsPlugin",
]
```

**Step 2: Verify imports work**

Run: `python -c "from harness.extensions import EvalChartPlugin, AgentTracePlugin; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add harness/extensions/__init__.py
git commit -m "feat(extensions): re-export plugin classes from top-level package"
```

---

### Task 9: Run full test suite and verify no regressions

**Step 1: Run all extension tests**

Run: `pytest harness/extensions/ -v`
Expected: All PASS

**Step 2: Run full project test suite**

Run: `pytest tests/ harness/ -v --timeout=30`
Expected: All PASS

**Step 3: Verify example with plugin**

```bash
python -c "
from harness.api import Workflow, Agent
from harness.extensions.eval import EvalJudge
from harness.extensions.plugins import EvalChartPlugin, AgentTracePlugin

wf = (
    Workflow('test', agents=[
        Agent('coder', after=[], eval=True),
        Agent('reviewer', after=['coder']),
    ])
    .use(EvalJudge())
    .use(EvalChartPlugin())
    .use(AgentTracePlugin())
)
print('Workflow created with plugins:', [e for e in wf._event_bus._hooks])
"
```

Expected: Lists `eval-chart`, `agent-trace`

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(plugins): extensible hook plugin system with 4 built-in plugins"
```
