# 04 — Testing layout

Each extension must ship with three categories of tests, in the order
below, in `test_<name>.py` next to the implementation.

## 1. Unit tests

Pure logic of the extension class with **all external work mocked**.
No real LLM calls, no disk IO, no subprocesses.

- Construct a fake `NodeCtx` / `ToolCtx` / `WorkflowCtx` with the
  data the extension cares about.
- For middlewares: call `await mw.before_node(ctx)` directly. Assert
  on the returned ctx / RejectAction / RetryAction.
- For hooks: call the method directly. Assert on side-effect
  (your test double).
- For mutators: call `mutate(workflow)` directly. Assert structure.

Cover at minimum:
- Happy path.
- No-op path (config below threshold, feature flag off).
- Validation errors in `__init__`.
- One failure mode where the contract returns a control action.

## 2. Integration tests

The extension on a real `Bus`, running through the public dispatch
methods. Still no LLM — use injectable summarizer/extractor/etc. that
you took as a constructor arg specifically so it could be replaced.

- `bus = Bus(); bus.register(YourExt(...))`
- `await bus.run_middleware_chain("before_node", ctx)` / `await bus.run_hooks(...)`
- Verify it composes with at least one other no-op extension to prove
  priority and chaining work.

## 3. Off-state test

Required test name: `test_unregistered_has_no_effect` (or close).
Goal: prove that if a user doesn't `.use()` your extension, nothing
changes.

```python
@pytest.mark.asyncio
async def test_unregistered_has_no_effect():
    bus = Bus()  # nothing registered
    ctx = _make_ctx_with_state_that_would_be_affected()
    out = await bus.run_middleware_chain("before_node", ctx)
    assert ctx == out_before  # untouched
```

If your extension touches disk, also assert no files appeared after
running with empty bus.

## What you don't need

- End-to-end tests with a real LLM. Those live in `tests/` and run on
  demand; your extension's correctness must be demonstrable without them.
- UI tests. If your extension introduces frontend events (e.g.
  `ext.approval.requested`), document the contract in your SPEC.md
  and add a backend test that confirms the event is emitted.

## Running

```
pytest harness/extensions/<name>/
```

CI runs `pytest harness/extensions/` for every PR.
