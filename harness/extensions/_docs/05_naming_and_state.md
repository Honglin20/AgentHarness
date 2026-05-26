# 05 — Naming and state

## Naming

- Directory name = `snake_case` noun or short noun-phrase that says
  what the extension *is*. Examples: `compact`, `memory`, `eval`,
  `guardrail`, `budget`, `approval`, `tracing`, `cache`.
- Public class name = `PascalCase` user-facing verb or noun.
  Examples: `AutoCompact`, `FileMemory`, `EvalJudge`, `Guardrail`,
  `TokenBudget`, `ApprovalGate`, `OTelTracing`, `PromptCache`.
- `name` attribute = same as the directory, in `snake_case`. Used as
  the registry key and the metadata namespace.
- Avoid suffixes like `Manager`, `Handler`, `Service`, `Engine`.
  The user is calling it; pick a name that says what it *does*, not
  what it *is*.

## State isolation

Three kinds of state, three places to put them.

### Per-instance state

Attributes on `self`. Lifetime = the lifetime of the extension object.
Use for static configuration parsed in `__init__` and for caches that
should outlive a single workflow (e.g. `PromptCache._lru`).

### Per-workflow state

`ctx.workflow.metadata[<your name>]` (a dict you fully own).
Lifetime = one workflow run. Cleared automatically with the workflow.
Use for counters, timers, accumulated facts. Example: `TokenBudget`
keeps `{"input": int, "output": int, "started_at": float}` here.

### Per-node state

`ctx.metadata[<your name>]`. Lifetime = one agent step. Use for
breadcrumbs to other middleware in the same step (rare) or for
observability to surface to hooks running later in the chain
(e.g. `AutoCompact` writes `{"compacted": True, "dropped_messages": N}`).

## Strict rules

- **Never** read or write metadata under another extension's name. If
  you need data from another extension, take it as a constructor arg
  or a function passed in — not via shared state.
- **Never** import another extension. Cross-extension coupling kills
  the plug-and-play property.
- **Never** mutate `ctx.upstream_outputs`. It is contractually read-only.
- **Never** rebind `ctx` itself. Mutate its fields and return it. The
  engine assumes the same object identity throughout the chain so it
  can keep a reference for the next phase.

## When you genuinely need cross-extension awareness

Don't. Instead:

1. Lift the shared concept into the core (`harness/extensions/base.py`
   gets a new optional field, e.g. `NodeCtx.token_estimate`). This is
   what `08_when_engine_changes_are_needed.md` is about.
2. Or: split your feature so each side owns one extension and they
   compose through configuration (the user wires them in `.use(...).use(...)`).
