# TokenBudget

State: 🚧 To implement.

## What it does

Enforce token / cost / wall-clock ceilings so a runaway workflow can't
silently burn the API key. When the limit is hit, gracefully stop the
workflow with a clear error instead of letting it spiral.

## Extension type

`BaseHook` for accounting + `BaseMiddleware` for enforcement.

- Hook: `on_node_end` reads token_usage from the result, updates running totals.
- Middleware: `before_node` checks "would the next step likely blow the
  budget?" and returns `RejectAction` if so.

## Public API

```python
from harness.extensions.budget import TokenBudget

wf = Workflow(...).use(TokenBudget(
    per_workflow_tokens=500_000,
    per_agent_tokens=100_000,
    per_workflow_wall_seconds=600,
    cost_per_million_input=3.0,    # optional, for $ accounting
    cost_per_million_output=15.0,
    on_exceed="reject",            # or "warn" (log + continue)
))
```

## Behavior

- Maintain running counters keyed by `(workflow_id, agent_name)` in
  `ctx.workflow.metadata["budget"]`.
- `on_node_end` — add `token_usage` from `agent_run.usage` to counters.
  Emit `ext.budget.tick` with current totals (UI shows progress bar).
- `before_node` — if any counter ≥ its limit, return `RejectAction(reason=...)`.
- Wall-clock: store `start_ts` in workflow metadata at first `before_node`;
  check `now - start_ts` against `per_workflow_wall_seconds`.

## Tests required

| File | Purpose |
|---|---|
| `test_budget.py::test_counter_accumulates_across_nodes` | Two nodes → counter sums |
| `test_budget.py::test_reject_when_workflow_limit_hit` | Counter ≥ limit → next node rejected |
| `test_budget.py::test_reject_when_agent_limit_hit` | Per-agent cap hit → that agent's next call rejected |
| `test_budget.py::test_warn_mode_does_not_reject` | mode=warn → only emit, no block |
| `test_budget.py::test_unregistered_no_state_leak` | Not on bus → no counters created |

## Open questions

- [ ] How to estimate *before* the call? v1: don't — react only after.
  Trade-off: one over-budget call slips through. Acceptable.
- [ ] $ accounting precision — use model-specific pricing tables. v1:
  user passes the two rates; tables come later.

## Acceptance

- A workflow with `per_workflow_tokens=1000` and an agent that produces
  ~600 tokens succeeds on first call, gets rejected on second.
- Removing `TokenBudget` from `.use()` chain leaves no counters or events.
