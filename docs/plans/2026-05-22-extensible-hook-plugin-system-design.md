# Extensible Hook Plugin System — Design

Date: 2026-05-22

## Problem

The extension system defines three types (Hook, Middleware, GraphMutator),
but Hook has **zero production implementations**. Meanwhile, chart rendering
and other observational features are hardcoded inside engine node functions
(`_make_judge_node_func` in `macro_graph.py`). This makes it impossible for
users to opt in/out of these features or extend with new ones (agent trace
visualization, performance metrics, etc.) without editing engine code.

## Design Decision

**Enhance existing Hook with side-channel emit capability.** No new base
class, no fourth extension type. Plugins are just `BaseHook` subclasses
that call `ctx.emit()` to produce artifacts.

### Why not a new BasePostProcessor type?

Hook and the hypothetical PostProcessor would share the same lifecycle
(`on_node_end`, `on_tool_call`, etc.) and the same "cannot modify main
data flow" constraint. A separate type would double the registration,
dispatch, and Bus machinery for no semantic gain.

### Why not use GraphMutator (insert post-processing nodes)?

Too heavy. Rendering a chart shouldn't require inserting a DAG node and
running a full agent step. Observational artifacts should be produced
_inline_ during the existing node lifecycle, not as separate execution
units.

## Architecture

### 1. Side-channel emit on NodeCtx

```python
@dataclass
class NodeCtx:
    # ...existing fields unchanged...
    _side_effects: list[dict] = field(default_factory=list, repr=False)

    def emit(self, event_type: str, payload: dict) -> None:
        """Produce an observational artifact (chart, metric, trace, etc.).

        Safe to call from Hook.on_node_end — does not affect the main
        data flow. Artifacts are flushed to the Bus after all hooks
        complete.
        """
        self._side_effects.append({"type": event_type, "payload": payload})
```

### 2. Bus flushes side effects after run_hooks

```python
async def run_hooks(self, method, *args) -> None:
    # ...existing: gather all hooks...
    # NEW: flush any side effects produced by hooks
    if args and isinstance(args[0], NodeCtx):
        for effect in args[0]._side_effects:
            self.emit(effect["type"], effect["payload"])
        args[0]._side_effects.clear()
```

### 3. Plugin directory

```
harness/extensions/plugins/
├── __init__.py              # Re-export all plugin classes
├── eval_chart.py            # Judge score → line chart
├── agent_trace.py           # Agent execution trace diagram
├── reasoning_viz.py         # Agent reasoning process visualization
└── perf_metrics.py          # Token usage, latency, tool-call metrics
```

Each plugin is a `BaseHook` subclass following the same pattern:

```python
class EvalChartPlugin(BaseHook):
    name = "eval-chart"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        if not ctx.agent_name.startswith("_judge_"):
            return
        # ...extract score from output/metadata...
        ctx.emit("chart.render", { ... })
```

User enables plugins declaratively:

```python
wf = (
    Workflow("research", agents=[...])
    .use(EvalChartPlugin())       # opt-in: score charts
    .use(AgentTracePlugin())      # opt-in: trace diagram
    # not listed = not enabled
)
```

### 4. Migration: hardcoded chart → EvalChartPlugin

Current chart rendering in `_make_judge_node_func` (macro_graph.py:649-660):

```python
# BEFORE: hardcoded in engine
if review.score is not None:
    score_history.append(review.score)
    if bus:
        bus.emit("chart.render", { ... })
```

After migration, the judge node function only writes score to metadata:

```python
# AFTER: engine writes metadata only
metadata[judge_name]["score_history"] = score_history
```

`EvalChartPlugin.on_node_end` reads the metadata and emits the chart.

## Capability boundary

| | Main data flow | Side-channel artifacts | DAG structure |
|---|---|---|---|
| Hook / Plugin | Read-only | Read-write (via `ctx.emit`) | No |
| Middleware | Read-write | Read-write (via `ctx.emit`) | No |
| GraphMutator | No | No | Read-write |

- **Main data flow**: `output`, `prompt`, `messages`, `tool_args`
- **Side-channel artifacts**: charts, metrics, traces, logs — anything
  produced via `ctx.emit()` and delivered through the Bus's `emit()` to
  WebSocket subscribers.

Middleware can also use `ctx.emit()` (e.g., AutoCompact could emit a
"compaction happened" metric), but that's additive — the middleware
contract doesn't change.

## Detailed plugin specs

### EvalChartPlugin

- **Trigger**: `on_node_end` for nodes whose name starts with `_judge_`
- **Input**: `ctx.metadata[agent_name]` → reads `score_history`
- **Output**: `ctx.emit("chart.render", {chart_type: "line", ...})`
- **State**: score_history stored in `ctx.metadata["eval-chart"]`

### AgentTracePlugin

- **Trigger**: `on_node_end` for every node
- **Input**: `ctx.agent_name`, `ctx.workflow.node_id`, `output`
- **Output**: `ctx.emit("trace.step", {agent, tools_used, duration, status})`
- **Frontend**: Consumes `trace.step` events to build execution trace
  diagram (Recharts timeline or ReactFlow subgraph)

### ReasoningVizPlugin

- **Trigger**: `on_node_end` for every node
- **Input**: `ctx.messages` (the full conversation including reasoning)
- **Output**: `ctx.emit("reasoning.render", {agent, steps, decision_points})`
- **Note**: Depends on the LLM outputting chain-of-thought. Best-effort
  extraction; no-op if no reasoning trace is found.

### PerfMetricsPlugin

- **Trigger**: `on_node_end` and `on_tool_call`
- **Input**: `ctx.metadata[agent_name]` → `duration_ms`, `token_usage`
- **Output**: `ctx.emit("chart.render", {chart_type: "bar", ...})` for
  token usage; `ctx.emit("metric.report", {...})` for latency stats

## What changes and what doesn't

### Changes

| File | What |
|------|------|
| `extensions/base.py` | Add `_side_effects` field and `emit()` method to `NodeCtx` |
| `extensions/bus.py` | Flush `_side_effects` after `run_hooks()` completes |
| `extensions/plugins/` | New directory with 4 plugin files + `__init__.py` |
| `engine/macro_graph.py` | Remove hardcoded chart rendering from `_make_judge_node_func` |

### No changes

| Component | Why |
|-----------|-----|
| `BaseHook` signature | Plugins subclass it as-is |
| `BaseMiddleware` | Unchanged; can optionally use `ctx.emit()` |
| `BaseGraphMutator` | Unchanged |
| `Bus.register()` | Works with `BaseHook` subclasses automatically |
| `Workflow.use()` | No change needed |
| `render_chart()` in `tools/chart.py` | Still used internally; plugins call `ctx.emit()` which routes through Bus |

## Open questions

- [ ] Should `WorkflowCtx` also get `emit()` for workflow-level artifacts?
- [ ] Should plugins have an `enabled` flag like `AutoCompact` does?
- [ ] Should `AgentTracePlugin` also hook `on_node_start` to record
      pre-execution state, or is `on_node_end` sufficient?
