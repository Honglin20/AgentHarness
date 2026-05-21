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
2. "Anyone want to **know** what's about to happen?" → Hooks

Plus, before the state machine even starts, it asks:

3. "Anyone want to **rewrite the graph itself**?" → GraphMutator

The bus answers, the engine acts. Extensions are the answers.

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
