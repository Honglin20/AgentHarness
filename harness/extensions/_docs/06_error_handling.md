# 06 — Error handling

The single most important rule: **a broken extension must not break the
workflow**. Users will install third-party extensions. If a broken one
crashes the engine, the system is unusable.

## What the bus does for you

- Hook exceptions: caught, logged (`logger.exception`), and emitted as
  an `ext.error` event with `{extension, phase, error}`. The remaining
  hooks for the same event still run.
- Middleware exceptions: caught, logged, emitted as `ext.error`. The
  remaining middleware in the chain still run, with the **un-mutated
  ctx from before your call**. (Your work is discarded.)
- GraphMutator exceptions: caught, logged, emitted as `ext.error`. The
  workflow is built from the un-mutated definition.

You do not need to wrap your code in `try/except` to make this work.
The bus handles it.

## What you should still do

- Validate `__init__` arguments and raise `ValueError` with a clear
  message. This runs eagerly when the user calls `.use(...)`, so they
  see the error at setup, not during the first node call.
- For runtime errors that you can recover from internally (e.g. the
  summarizer returned an empty string), handle them yourself and emit
  a custom event (`ext.<name>.warning`) so users can debug.
- Use `RejectAction` to intentionally fail a node, with a `reason`
  string the user will read in the run history. Don't `raise` for
  business-logic rejection.

## What the user sees

Every `ext.error` and `ext.warning` event is forwarded to the WebSocket
clients. The frontend shows a small banner like:

> ⚠️ Extension `auto_compact` failed in `before_node`: <error message>

The workflow still continues. The user can decide whether to disable
the extension or fix it.

## What the user expects

- Single-source failure messages. If your extension fails repeatedly
  for the same reason, emit the event once per workflow and accumulate.
- Failures attributable. The `extension` field in the event lets the
  UI link straight to your config in the workflow definition.

## Anti-patterns

- `except Exception: pass` inside your own code. If you swallow it,
  the bus can't log it.
- Logging at `ERROR` level for every call. Logs are not free; pick
  carefully.
- Raising `KeyboardInterrupt` / `SystemExit` from inside an extension.
  These propagate past `except Exception`. Don't.
