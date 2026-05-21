# 02 — Choosing an extension type

Three contracts; pick by intent, not by convenience.

## Decision tree

```
Do you need to modify the DAG itself
(add nodes, change edges)?
  ├── yes → GraphMutator
  └── no
      │
      Do you need to change what the agent
      sees, what it outputs, or block a step?
        ├── yes → Middleware
        └── no  → Hook
```

## Hook — observe only

Use when you only want to **read**: log to a file, send a metric, write
to a trace exporter, persist something for later. Cannot stop the
workflow, cannot change the prompt, cannot delay anything.

- Concurrent: all hooks for the same event fire via `asyncio.gather`.
- Exceptions are caught, logged, and emitted as `ext.error`. Your hook
  failing never breaks the workflow.
- Slow hooks slow down the engine — keep them quick or off-load.

## Middleware — mutate or reject

Use when you need to **change** the context flowing through the engine,
or **block** a step. Three phases:

| Phase          | When                              | Mutate         | Control actions          |
|----------------|-----------------------------------|----------------|--------------------------|
| `before_node`  | After prompt built, before LLM    | `prompt`, `messages`, `metadata` | `RejectAction` |
| `before_tool`  | Right before a tool runs          | `tool_args`, `metadata`          | `RejectAction` |
| `after_node`   | After LLM returns, before persist | wrap/replace `output`            | `RetryAction`  |

- Serial: middlewares run one at a time in `priority` order.
- `before_*` runs low-priority first; `after_*` runs high-priority first.
  (Think of middlewares as layers — early in, late out.)
- A single `RejectAction` short-circuits the rest of the chain.
- `RetryAction` from `after_node` is recognized; full retry execution
  is engine work (currently logs only — see `08_when_engine_changes...`).

## GraphMutator — rewrite the DAG

Use when the new capability is a *structural* change to the workflow,
not a per-step intervention. Examples: insert an evaluator node after
every agent marked `eval=True`; expand one agent into a sub-graph of
specialists; remove a node based on inputs.

- Runs once, at `Workflow.compile()` time, before the engine builds
  the LangGraph state graph.
- Return value replaces the workflow. Mutate-in-place is also fine
  but prefer building a new list of agents.
- Multiple mutators run in registration order. Each sees the previous
  one's output.
- Exceptions are caught and emitted as `ext.error`; compilation continues
  with the un-mutated workflow.

## Composite extensions

Some features need two contracts (e.g. Memory: inject via Middleware,
extract via Hook). That's fine — define one class that inherits from
both `BaseMiddleware` and `BaseHook`, or define two coordinated classes
in the same package. Prefer one class with the `name` attribute set
identically so users register once.
