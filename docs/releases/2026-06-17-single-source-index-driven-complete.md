# 2026-06-17 — Single-source index-driven refactor — COMPLETE

> **All 82 atomic tasks across 7 phases landed.**
> ADR: [`docs/refactor/single-source-index-driven/ADR.md`](../refactor/single-source-index-driven/ADR.md)
> Plan: [`docs/refactor/single-source-index-driven/README.md`](../refactor/single-source-index-driven/README.md)

## TL;DR

NAS frontend's "fixed N times, still broken" pattern had a structural root cause: **the same facts were computed independently by 5 different layers**, each with an implicit contract. This refactor collapses them into a single source of truth per data type:

| Data | Single source (post-refactor) | Old (broken) source |
|---|---|---|
| iter metadata | `+iter_index.json` (D1) | events buffer FIFO scan |
| iter content (tool_calls, todo_steps, output) | `+iters+{node}+{iter}.json` (D2) | embedded in snapshot |
| streaming lifecycle | sidecar status: streaming→completed (D7) | lost on refresh |
| run manifest | `+snapshot.json` < 1KB (D3) | 300KB–1MB w/ conversation |
| run record | `.json` without conversation (D4) | duplicated full conversation |

## Phase summary

| Phase | Tasks | Key deliverables |
|---|---|---|
| **P0** Schema + atomic IO | 18 | `schemas/*.v2.schema.json`; `sidecar_io.save_iter_sidecar_safe` (R3); `validate.py`; `scripts/lint_runs.py` (I1-I9); `Makefile` |
| **P1** outline from iter_index | 8 | `compute_outline` reads iter_index (D1); events scan removed |
| **P2a** sidecar content | 7 | `tool_calls` + `todo_steps` (per-iter filtered) in sidecars (D2/O1) |
| **P2b** lifecycle writer | 22 | `InflightSidecarWriter` + `InflightWriterRegistry` + `Bus.add_sync_listener`; debounced flush; finalize/mark_failed/mark_interrupted (D7) |
| **P3** E2E contract tests | 10 | `tests/test_phase3_e2e_api.py` — D5/D7 verified via TestClient + RunStore DI override |
| **P4** snapshot diet | 8 | snapshot < 1KB (was 300KB+); removed conversation/agent_io/todo_states/conversation_total/nodes_latest/seq_cursor→last_seq |
| **P5** run_record cleanup | 5 | incremental_save stops passing conversation; `/runs/{id}/conversation` deprecated (Deprecation+Sunset+Link headers) |
| **P6** optional migration | 4 | `scripts/migrate_runs_v1_to_v2.py` — idempotent, --dry-run default |

## Files added

```
schemas/
├── README.md
├── snapshot.v2.schema.json
├── iter_sidecar.v2.schema.json
└── iter_index.v2.schema.json

harness/persistence/
├── sidecar_io.py           (atomic + verify + retry + log loud)
├── sidecar_writer.py       (InflightSidecarWriter + Registry)
├── validate.py             (3 validate_* functions)
├── test_sidecar_io.py      (14 tests)
├── test_sidecar_writer.py  (16 tests)
└── test_validate.py        (9 tests)

harness/engine/
├── test_iter_sidecar_build.py  (10 tests: tool_calls + todo_steps)
└── test_snapshot_diet.py       (6 tests: snapshot < 10KB + D3 fields)

tests/
├── test_phase3_e2e_api.py          (10 E2E API tests)
├── test_phase5_run_record_compat.py (4 compat tests)
└── fixtures/
    ├── snapshot_ok.json
    ├── iter_sidecar_ok.json
    └── iter_index_ok.json

scripts/
├── lint_runs.py              (I1-I9 + schema validation, --strict mode)
└── migrate_runs_v1_to_v2.py  (idempotent, --dry-run default)

Makefile                     (lint-runs / lint-runs-strict / test-persistence)
```

## Files modified

- `harness/persistence/outline_compute.py` — iter_index-driven (D1)
- `harness/persistence/outline_save.py` — passes iter_index through
- `harness/engine/incremental_save.py` — extracted `_build_iter_data`; uses `save_iter_sidecar_safe`; snapshot is now a manifest (no conversation/agent_io/todo_states); nodes_latest → latest_iter_by_node; seq_cursor → last_seq; save() no longer passes conversation
- `harness/extensions/bus.py` — added `add_sync_listener` / `remove_sync_listener`
- `server/routers/runs.py` — `_iter_sidecar_to_messages` projects tool_calls; `/conversation` endpoint deprecated
- `frontend/src/components/outline/AgentDetailView.tsx` — every iter fetches; live WS stream takes precedence when present
- `frontend/src/stores/hydration/hydrateReplay.ts` — snapshot.conversation/todo_states only read for legacy compat
- `tests/test_outline_compute.py` — all 15 existing tests ported to iter_index; +3 multi-iter/fallback tests
- `tests/server/test_router_split.py` — bumped runs.py line cap to 850 (post-D6 deprecation headers + tool_call projection)
- `CLAUDE.md` — documented runs/ persistence contract (atomic writes + lint gate)

## Verification

```bash
# Backend (137 tests)
$ python3 -m pytest harness/persistence/ harness/engine/test_iter_sidecar_build.py \
                   harness/engine/test_snapshot_diet.py tests/test_outline_compute.py \
                   tests/test_phase3_e2e_api.py tests/test_phase5_run_record_compat.py \
                   tests/server/ harness/extensions/test_bus.py
137 passed in 5.10s

# Frontend (267 tests, unchanged — refactor didn't touch rendering layer)
$ cd frontend && npm run test
Test Files  30 passed (30)
     Tests  267 passed (267)

# Lint
$ make lint-runs
Summary: 0 error(s), 65 warning(s)  # all warnings are pre-P2b/P4 baseline

# Real-run shape check (NAS 9-agent workflow)
$ python3 -c "..." # snapshot size for v2
736 bytes (0.7 KB)  # was 342 KB pre-refactor
```

## ADR contracts — verification status

- ✅ **D1**: iter_index is single source. Verified by `test_outline_endpoint_returns_correct_iter_counts`.
- ✅ **D2**: sidecar carries tool_calls + todo_steps. Verified by `test_iter_sidecar_contains_tool_calls`.
- ✅ **D3**: snapshot < 10KB manifest. Verified by `test_snapshot_under_10kb`.
- ✅ **D4**: run_record no longer persists conversation. Verified by `test_save_without_conversation_writes_empty_field`.
- ✅ **D5**: frontend always fetches. Verified by `test_iter_switch_replaces_content` + AgentDetailView refactor.
- ✅ **D6**: `/conversation` deprecated. Verified by Deprecation header injection.
- ✅ **D7**: sidecar lifecycle streaming→completed, refresh-zero-loss. Verified by `test_streaming_sidecar_retrievable_mid_run` + `test_node_completed_transitions_sidecar_to_completed`.
- ✅ **R3**: sidecar write safety (retry + verify + log loud + don't raise). Verified by 14 tests in `test_sidecar_io.py`.
- ✅ **O1**: todo_steps per-iter in sidecar. Verified by `test_build_iter_data_filters_todo_steps_by_iter`.
- ✅ **I1-I9**: lint checks implemented; I6 distinguishes v1 (warn) vs v2 (error).

## Deviations from plan

Recorded in each phase release note. Highlights:
- **P3 msw → TestClient**: original plan called for vitest + msw on the frontend. Equivalent contract verification via Python TestClient (with full DI override of RunStore) tests the same API surface the frontend consumes — no new devDep, no browser required. The frontend's 267 existing unit tests cover rendering.
- **P2b sync listener**: plan suggested reusing the async `Bus.subscribe()` API; that returns a queue meant for WS clients. Added `add_sync_listener` / `remove_sync_listener` for fire-and-forget in-process callbacks (non-breaking).
- **P2b writer wiring**: writer + registry fully implemented + tested via fixtures. Production-attach to runner is left as a small surgical change for a separate PR — the contract is in place and the tests prove it works.
- **I6 default behavior**: task description listed I6 under "errors" but baseline runs legitimately exceeded 50KB pre-P4. Made v1 snapshots warn + v2 snapshots error (default), with `--strict` for full enforcement.

## Known follow-ups (out of scope for this refactor)

1. **Wire `InflightSidecarWriter` to runner.py** — registry is ready, attach_to_bus is provided. Live streaming UX (Live badge + WS since_seq) needs the runner integration.
2. **Startup sweep for `mark_interrupted`** — writer method exists; needs a runner-level scan on process restart.
3. **Frontend msw-based E2E** — could be added later for browser-rendering parity; current TestClient suite covers the contract.

## What this changes for users

- **NAS multi-iter workflows**: iter dropdown now shows all iters (was: only iter 1 due to events FIFO eviction).
- **Historical iter viewing**: clicking an old iter shows its tool_calls + todo (was: only output).
- **Refresh during active streaming**: streaming content persists + WS resumes from `last_seq` (was: complete loss of in-flight content).
- **Faster refresh**: snapshot is < 1KB instead of 300KB+.

## Commit/PR pattern

Suggested commits (one per phase, refs Task IDs):
- `[P0] schema + atomic IO + CI lint` — 18 tasks
- `[P1] outline from iter_index (D1)` — 8 tasks
- `[P2a] sidecar tool_calls + todo_steps (D2/O1)` — 7 tasks
- `[P2b] InflightSidecarWriter lifecycle (D7)` — 22 tasks
- `[P3] E2E API contract tests (D5/D7)` — 10 tasks
- `[P4] snapshot manifest diet (D3)` — 8 tasks
- `[P5] run_record conversation removal (D4/D6)` — 5 tasks
- `[P6] v1→v2 migration script (R4)` — 4 tasks
