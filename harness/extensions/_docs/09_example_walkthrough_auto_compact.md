# 09 — Walkthrough: AutoCompact

The canonical end-to-end example. Read this once after `01`–`08` and
you'll have the full pattern in your head.

## The problem

A workflow grows long. The agent's message history blows past the
model's context window. We want to summarize the early parts so the
agent keeps working without losing the thread.

## Which extension type

We need to **change `ctx.messages` before the LLM call**. That's a
mutation, so → Middleware. `before_node` phase.

## File layout

```
harness/extensions/compact/
├── __init__.py          ← re-exports `AutoCompact`
├── auto_compact.py      ← the class
├── test_auto_compact.py ← unit + integration + off-state tests
└── SPEC.md              ← (this case: empty; design is in the docstring)
```

## The class shape

```python
class AutoCompact(BaseMiddleware):
    name = "auto_compact"
    priority = 100         # late: let memory/guardrail run first

    def __init__(
        self,
        threshold_tokens: int = 8000,
        keep_recent: int = 4,
        summarizer: Callable[[str], Awaitable[str]] | None = None,
        summarizer_model: str | None = None,
        token_counter: Callable[[str], int] | None = None,
        enabled: bool = True,
    ):
        if keep_recent < 1: raise ValueError(...)
        if threshold_tokens < 100: raise ValueError(...)
        # store
```

Things this demonstrates:
- `name` matches the directory.
- All config in `__init__` kwargs.
- `enabled` flag for runtime disable.
- Heavy dependency (the LLM summarizer) is injectable so tests can
  pass in a fake without going near a real network call.
- Validation raises clearly.

## The behavior

```python
async def before_node(self, ctx):
    if not self.enabled:
        return ctx
    if len(ctx.messages) <= self.keep_recent:
        return ctx
    total = sum(self._count(self._stringify(m)) for m in ctx.messages)
    if total < self.threshold_tokens:
        return ctx

    early = ctx.messages[:-self.keep_recent]
    recent = ctx.messages[-self.keep_recent:]
    summary = await self._summarize(self._join(early))
    ctx.messages = [{"role": "system", "content": f"[Compacted...]: {summary}"}, *recent]

    ctx.metadata.setdefault(self.name, {})
    ctx.metadata[self.name]["compacted"] = True
    ctx.metadata[self.name]["dropped_messages"] = len(early)
    return ctx
```

Things this demonstrates:
- Early returns for every no-op path; no work done if nothing needed.
- Mutate `ctx.messages` in place; return the same `ctx`.
- Write to your namespace under `ctx.metadata[self.name]`.
- No exception handling — the bus does that.

## The tests

```python
# Unit
async def test_no_op_below_threshold(): ...
async def test_compacts_when_over_threshold(): ...
async def test_disabled_flag_skips_work(): ...
def test_invalid_params_raise(): ...

# Integration (on a real Bus)
async def test_integration_with_bus(): ...
async def test_runs_after_lower_priority_middleware(): ...

# Off-state
async def test_unregistered_has_no_effect(): ...
```

Things this demonstrates:
- Unit tests construct a fake `NodeCtx` and call the method directly.
- Integration tests register on a real `Bus` and call
  `bus.run_middleware_chain("before_node", ctx)`.
- Off-state test proves an empty bus is a pure passthrough.
- The summarizer is a callable so tests use a `_fake_summarizer` that
  doesn't touch the network.

## The user-facing API

```python
wf = (
    Workflow("research", agents=[...])
    .use(AutoCompact(threshold_tokens=8000, keep_recent=4))
)
```

Fluent. Optional. Removable. That's the bar for every extension.

## What it can't do today, and why

`ctx.messages` only contains what middleware put there, not the real
Pydantic AI message history (which lives inside `agent_run.ctx.state`).
So `AutoCompact`'s "real" effect today is limited to compacting things
other middleware injected (e.g. Memory's blob) plus the initial user
message.

This is a known engine-contract limitation, tracked in
`08_when_engine_changes_are_needed.md` under "`MessageView`". When that
contract addition lands, `AutoCompact` works for the full conversation
**without changing its source code**. That's the test of good extension
design: it generalizes when the contract grows.
