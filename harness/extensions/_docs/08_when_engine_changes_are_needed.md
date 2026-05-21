# 08 — When engine changes are needed

The three contracts cover most extensions. When they don't, the
escape hatch is small, intentional, and reviewed.

## Symptoms that you've hit a contract limit

- You need a control action that isn't `RejectAction` or `RetryAction`
  (e.g. `SkipAction` to short-circuit with a cached output — see
  `cache/SPEC.md`).
- You need to see data that's not on `NodeCtx` (e.g. full Pydantic AI
  message history with tool turns, before/after a specific tool).
- You need a callback at a moment the bus doesn't currently emit
  (e.g. "between two retries within a single agent call").

## What to do

1. Open an issue describing the symptom with at least two extensions
   that would benefit. **One extension demanding an engine change is
   not enough**; the contract is supposed to be sharp.
2. Propose the smallest possible contract addition. Examples of small:
   - New optional field on `NodeCtx` (default `None`).
   - New control action class in `base.py` + one line of dispatch in
     `bus.run_middleware_chain`.
   - New event in the lifecycle (e.g. `on_node_retry`) with `BaseHook`
     stub method.
3. Update `01_overview.md`'s mental model paragraph if the new
   addition shifts it.
4. Bump the bus version comment in `bus.py` so old extensions warn
   if they expect an older contract.

## What not to do

- Add a feature flag to `MacroGraphBuilder.__init__` for "your
  extension's needs". The builder must remain extension-agnostic.
- Reach into `pydantic_ai` internals through the extension. If you
  need it, lift it into the contract.
- Import from `server/` inside an extension. Extensions are pure
  `harness/`; they must work in CLI mode without the FastAPI app.

## What's already known to need contract additions

- `SkipAction(output=cached)` — for PromptCache full short-circuit (v2).
- `MessageView` — a proper read-only wrapper around Pydantic AI's
  message history so AutoCompact can do real history compression
  (v2). Today, `ctx.messages` only contains what middleware put there,
  not the real LLM history.
- `on_tool_arg_validated` — a callback after tool args parse but
  before execution, for fine-grained ApprovalGate (v2).

Each of these will land in `base.py` only when at least one concrete
extension demands it.
