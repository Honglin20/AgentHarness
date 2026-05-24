# 01 — Overview

Extensions live in `harness/extensions/<name>/`. The engine knows
nothing about any specific extension; it only knows the three contracts
defined in `harness/extensions/base.py`. This means new capability =
new subdirectory, no engine edits.

## What to read first

1. This file — what the system is.
2. `02_choosing_extension_type.md` — Hook vs Middleware vs GraphMutator.
3. `03_authoring_checklist.md` — the rules every PR must satisfy.
4. `04_testing_layout.md` — required tests.
5. `05_naming_and_state.md` — naming, state isolation, namespacing.
6. `06_error_handling.md` — how failures must surface.
7. `07_observability.md` — how to emit events the UI can consume.
8. `08_when_engine_changes_are_needed.md` — what to do when the
   contract isn't enough.
9. `09_example_walkthrough_auto_compact.md` — the canonical example.

## Mental model

The engine is a state machine. At every transition it asks the Bus
two questions:

1. "Anyone want to **change** what's about to happen?" → Middleware
2. "Anyone want to **know** what's about to happen?" → Hooks / Plugins

Plus, before the state machine even starts, it asks:

3. "Anyone want to **rewrite the graph itself**?" → GraphMutator

The bus answers, the engine acts. Extensions are the answers.

## Why three types — not two, not four

The three-way split is grounded in **what each type can affect**, not just
"what it can do":

| | Main data flow | Side-channel artifacts | DAG structure |
|---|---|---|---|
| Hook / Plugin | Read-only | Read-write | No |
| Middleware | Read-write | Read-write | No |
| GraphMutator | No | No | Read-write |

**Hook and Middleware are NOT merged** because the "cannot modify main data
flow" constraint gives Hook a distinct safety guarantee: registering a Hook
can never break the workflow. This matters for Plugins (chart rendering,
metrics, tracing) — users trust that `.use(EvalChartPlugin())` is
zero-risk.

**Hook is not a fourth type** — Plugins are just Hooks with side-channel
emit capability. Same base class, same registration, same dispatch. The
only addition is `ctx.emit()` for producing charts, events, and other
observational artifacts.

### Why not merge Hook into Middleware?

A Middleware that doesn't mutate ctx/output is functionally equivalent to a
Hook. But the **contract distinction** matters:

- Hook failures are isolated (concurrent, swallow exceptions, never block).
- Middleware failures can short-circuit the chain (RejectAction / RetryAction).
- Hook registration carries the implicit promise: "this is safe to add."
- Middleware registration carries the implicit promise: "this may alter behavior."

Blurring that line would force users to audit every extension for side effects.
The three-type model makes the capability boundary explicit.

## What you'll never do

- Edit `harness/engine/macro_graph.py` to add your feature.
- Import from another extension. Each one is self-contained.
- Read or write another extension's state. Use your own namespace in
  `ctx.metadata[<your name>]`.
- Make extension behavior depend on registration order beyond what
  `priority` already controls.
- Add a feature that only works when your extension is installed *and*
  some other one is too. (Composition must emerge from the contracts,
  not from hidden assumptions.)
