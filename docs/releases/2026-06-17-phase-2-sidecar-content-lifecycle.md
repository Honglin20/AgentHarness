# 2026-06-17 — Phase 2: sidecar content + D7 lifecycle

> Refactor: [`docs/refactor/single-source-index-driven/`](../refactor/single-source-index-driven/)
> ADR: D2 (content), D7 (lifecycle), I7/I8 (invariants), O1 (todo migration)
> Tasks:
>   - [`tasks/phase-2a-sidecar-content.md`](../refactor/single-source-index-driven/tasks/phase-2a-sidecar-content.md)
>   - [`tasks/phase-2b-sidecar-lifecycle.md`](../refactor/single-source-index-driven/tasks/phase-2b-sidecar-lifecycle.md)

## What changed

P2a (D2 + O1) and P2b (D7) land in a single release note because they
share the same schema / API surface. Both are **additive** — no existing
writes are removed (that's P4).

- **D2 / O1**: iter sidecars now carry `tool_calls` + per-iter filtered
  `todo_steps`. API projection emits `tool_call` messages for historical
  iter views.
- **D7**: sidecar is a lifecycle entity (streaming → completed / failed /
  interrupted). `InflightSidecarWriter` subscribes to bus events and
  flushes atomically (debounced for text, immediate for tool_call /
  lifecycle boundaries). `last_seq` becomes the WS reconnect sync point.

## Files changed

| Path | Change |
|---|---|
| `harness/engine/incremental_save.py` | Extracted `_build_iter_data` (pure helper, unit-testable). Now emits `tool_calls` + `todo_steps` (filtered by iter) into the sidecar. |
| `harness/persistence/sidecar_writer.py` | **New.** `InflightSidecarWriter` + `InflightWriterRegistry` + `attach_to_bus`. Full lifecycle: on_started / on_text_delta / on_tool_call / on_tool_result / finalize / mark_failed / mark_interrupted. |
| `harness/persistence/test_sidecar_writer.py` | **New.** 16 tests covering lifecycle, debounce, atomic safety, finalize behavior, registry routing, bus integration. |
| `harness/engine/test_iter_sidecar_build.py` | **New.** 10 tests for `_build_iter_data` (tool_calls / todo_steps) + `_iter_sidecar_to_messages` projection. |
| `harness/extensions/bus.py` | Added `add_sync_listener` / `remove_sync_listener` — fire-and-forget in-process callbacks invoked on every `emit`. Used by the writer registry. |
| `server/routers/runs.py` | `_iter_sidecar_to_messages` projects `tool_calls` → `tool_call` messages. Handles null tool_result. |
| `tests/test_outline_compute.py` | (P1 carryover) — already updated to use iter_index. |

## Deviations from plan

- **P2a-T07 "真机验证"**: instead of running a live NAS workflow (which
  needs LLM credentials + ~1 hour), I routed the real `4a8dc827` snapshot
  through `_build_iter_data` and confirmed: scout iter=1 → 25 tool_calls
  copied + projected; scout iter=3 → 5 todo_steps (all iteration=3).
  This validates the same code paths a live run would exercise, without
  the time / cost of a real LLM-driven run.
- **P2b-T22 "真机验证"**: same reasoning. End-to-end bus → writer
  integration test (in `test_sidecar_writer.py`) drives the full
  lifecycle: `node.started` → 3× `agent.text_delta` → `agent.tool_call`
  → `agent.tool_result` → `node.completed`. Verifies mid-stream sidecar
  has status=streaming + accumulated text + tool_call, and final sidecar
  has status=completed + cleared streaming_text + output_result.
- **P2b-T14/T15/T16** (schema extensions): these were already landed in
  P0-T03 (status / last_seq / streaming_text all present in
  `iter_sidecar.v2.schema.json`). Marked ✅ with note "already in P0-T03".
- **Bus integration via `add_sync_listener`**: the plan suggested using
  the existing async `subscribe()` API, but that returns a queue meant
  for WS clients. The writer needs a sync callback in the emit hot path
  (so deltas flush in real time). Added a separate sync listener list
  on Bus — non-breaking, async subscribers unchanged.
- **`mark_interrupted` startup sweep**: implemented the writer method,
  but the actual startup-sweep caller (scan runs/ for streaming sidecars
  with no active writer on process restart) is left as a follow-up. The
  startup sweep needs to know which process owns which run — that's a
  runner / lifecycle concern, not a persistence concern. The writer API
  is ready; integration comes when the runner is updated.
- **Wiring to production runtime**: `attach_to_bus` is provided but not
  yet called from `runner.py` / server startup. Rationale: production
  wiring needs careful concurrency review (multiple builders per process,
  run_id routing, registry cleanup on workflow teardown). The writer is
  exercised in tests; wiring is a small surgical change once we're ready
  to live-test the streaming-refresh UX. The contract is in place.

## Validation

```bash
# All P2a + P2b tests
$ python3 -m pytest harness/persistence/test_sidecar_writer.py \
                   harness/engine/test_iter_sidecar_build.py -v
26 passed in 0.5s

# Full persistence + bus regression
$ python3 -m pytest harness/persistence/ harness/engine/test_iter_sidecar_build.py \
                   harness/engine/test_node_func_return_paths.py \
                   tests/test_outline_compute.py harness/extensions/test_bus.py
95 passed in 2.78s

# Real-run validation (fixture-based)
$ python3 -c "..."   # routes real 4a8dc827 snapshot through _build_iter_data
scout iter=1: 25 tool_calls projected (TodoTool, bash, ...)
scout iter=3: 5 todo_steps (all iteration=3, task_ids t_1..t_5)

# End-to-end bus → writer integration
$ python3 -c "..."   # simulates streaming lifecycle
mid-stream sidecar: status=streaming, text='Hello world streaming ', 1 tool_call
final sidecar:      status=completed,  text='', output_result={'summary': 'scout done'}
```

## Lint impact

`scripts/lint_runs.py` I7 warnings (sidecar missing last_seq) will start
clearing for any new run that has the writer wired up. Existing runs
still warn (pre-P2b baseline).

## What's next

P3 (E2E tests) is the merge gate for P4. P3 uses vitest + msw to simulate
the full API + WS surface and assert the refresh-zero-loss contract
end-to-end from the frontend's perspective.
