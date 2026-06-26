# Release: ErrorEvent Contract + Unified Error Flow (Phase 2 of executor-extensibility refactor)

**Date**: 2026-06-26
**Phase**: 2 of 3 (Phase 1 = Prompt Paradigm Split; Phase 3 = CliProfile abstraction)
**ADR**: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md)
**Plan**: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## What changed

Replaced the loose `raise RuntimeError(...)` pattern in `ClaudeCodeExecutor.run()` with a unified `ErrorEvent` dataclass + `ExecutorError` exception that carries the full failure context (stderr_tail / phase / executor / exit_code / retry_attempt / extra) end-to-end from executor → node_factory → server runner → cli_runner → frontend. Both sinks (CLI stderr + frontend toast/banner) now consume the same event source — eliminating the "scrape node.failed events to figure out which agent crashed under which backend" workaround.

| File | Change |
|---|---|
| `harness/engine/error_event.py` (new) | ErrorEvent dataclass + ExecutorError + build_workflow_error_payload + 2 helpers |
| `harness/extensions/bus.py` | CRITICAL_EVENT_TYPES += agent.executor_error (never FIFO-evicted) |
| `harness/engine/claude_code_executor.py` | 5 phases (timeout/spawn/stream/result_parse/schema_validate) each emit + raise ExecutorError |
| `harness/translator/stream_json.py` | result.is_error no longer emits node.failed; new system/api_retry + system/status translations |
| `harness/engine/node_factory.py` | except clause handles ExecutorError: enriches node.failed without re-emitting executor_error |
| `server/runner.py` + `harness/cli_runner.py` | workflow.error payload uses shared build_workflow_error_payload helper |
| `frontend/src/types/events.ts` + `eventSchemas.ts` | WorkflowErrorPayload + ExecutorErrorPayload + ApiRetryPayload + StatusUpdatePayload |
| `frontend/src/stores/workflowStore.ts` | handleWorkflowError + pushExecutorError + pushApiRetry + pushStatusUpdate actions |
| `frontend/src/contexts/workflow-context/routing/` | 3 new agent handlers + updated workflow.error handler (uses new payload) |
| `frontend/src/components/conversation/` | ExecutorErrorBanner + ApiRetryBadge + StatusBadge + pure helpers (testable) |

## Why

Three problems the previous architecture had:

1. **`claude -p` errors were invisible to the frontend**: `ClaudeCodeExecutor` raised `RuntimeError(stderr tail 500 chars)`, which `node_factory` caught and emitted as `node.failed` with the stringified exception. The frontend saw "claude exited code=1" but no stderr, no phase hint, no exit code structure. The CLI `harness run` path emitted a 2-field `{workflow_id, error}` payload — even less info.

2. **Translator + executor double-emitted node.failed**: when claude's stream-json returned `result.is_error=true`, the translator emitted `node.failed` AND the executor raised a separate `RuntimeError` that node_factory caught and re-emitted `node.failed`. Frontend saw two failure events for one underlying cause.

3. **No retry visibility during long gaps**: claude silently retries on 429 / 5xx. Users saw "stuck" with no feedback for 30+ seconds while the model retried under the hood.

## Solution

### ErrorEvent + ExecutorError (P2-T1)

```python
@dataclass
class ErrorEvent:
    workflow_id: str
    node_id: str | None
    agent_name: str | None
    executor: str
    phase: str           # spawn | stream | result_parse | schema_validate | timeout | runtime
    error_type: str
    error_message: str
    stderr_tail: str | None
    exit_code: int | None
    timed_out: bool
    retry_attempt: int | None
    ts: float
    extra: dict[str, Any]

class ExecutorError(RuntimeError):
    def __init__(self, message: str, error_event: ErrorEvent):
        super().__init__(message)
        self.error_event = error_event
```

Emit-uniqueness invariant: each error is emitted **exactly once** at its source. The executor emits `agent.executor_error` (critical) THEN raises ExecutorError. Downstream catches the exception to route / enrich — never re-emit.

### Phase dispatch (P2-T3)

`ClaudeCodeExecutor.run()` has 5 distinct error phases, each with a `_emit_and_raise_executor_error(phase=...)` call:

| Phase | Trigger | Frontend display |
|---|---|---|
| `timeout` | `claude_result.timed_out=True` | "(timed out)" marker |
| `spawn` | `exit_code != 0` | stderr_tail + exit_code |
| `stream` | `result.is_error=true` | api_error_status from `extra` |
| `result_parse` | exit 0 but no result event | generic "no result" |
| `schema_validate` | SchemaValidationError wrapped | schema field path |

Order matters: `timeout` checked BEFORE `spawn` because timeout implies exit_code=-1.

### Translator split (P2-T4)

- `_translate_result` `is_error=true` branch returns `[]` (no node.failed emit). The executor catches `is_error` via `_extract_pre_translate` and owns the emit.
- New `_translate_system_api_retry` → `agent.api_retry` event (retry_count / max_retries / wait_seconds / error_message)
- New `_translate_system_status` → `agent.status_update` event (status / duration_ms)
- Both new events are normal-priority (consistent with existing `agent.retry_attempted` pattern — final classified_failure subsumes them)

### Workflow.error shared payload (P2-T6/T7)

`build_workflow_error_payload(workflow_id, user_id, error, agents_snapshot, bus_buffer, batch_id)` lives in `harness/engine/error_event.py` and is called by **both** `server/runner.py::_run_workflow` and `harness/cli_runner.py::run_with_persistence`. Guarantees schema parity (ADR Decision 2 unified error flow) — frontend replay of CLI-run history sees the same rich fields live runs surface.

### Frontend (P2-T8/T9)

- **Toast feedback** at event time: `agent.executor_error` → red toast with phase tag + stderr_tail preview; `agent.api_retry` → amber toast with retry counter; `workflow.error` → red toast with executor + phase tags + stderr_tail
- **Inline banner** (persistent, refresh-safe via critical event): `ExecutorErrorBanner` renders phase / stderr_tail / exit_code / retry_attempt below AgentMessage content
- **Live badges**: `ApiRetryBadge` shows "Retrying (2/5) · waiting 4.5s · rate limited" during silent retries; `StatusBadge` shows liveness spinner during long gaps

Pure helpers extracted to `executorErrorHelpers.ts` for testability (vitest 4 + oxc parser limitation in this repo blocks JSX render tests — vitest.config.ts documents it).

## Acceptance

### Automated (282 backend + 25 frontend helper + 14 frontend store = 321 tests green)

| Test file | Cases | Locks |
|---|---|---|
| `tests/test_executor_error_event.py` | 28 | ErrorEvent fields / to_payload-from_payload round-trip / ExecutorError pickle / build_workflow_error_payload all branches / CLI-server parity |
| `tests/test_bus_critical_types.py` | 8 | agent.executor_error in CRITICAL_EVENT_TYPES / auto-resolves to critical / explicit override / typo fail-loud |
| `tests/engine/test_claude_code_executor_error_paths.py` | 12 | 5 phases emit + raise / emit-uniqueness parametrized / no-bus path / api_error_result capture |
| `tests/engine/test_node_factory_executor_error.py` | 5 | ExecutorError → no re-emit / node.failed enrichment / root re-raise / non-ExecutorError unchanged |
| `tests/translator/test_stream_json.py` | 37 | result.is_error returns [] / api_retry translated / status translated / unknown subtype defensive |
| `tests/server/test_runner_error_payload.py` | 10 | _lookup_agent_executor / payload shape via simulation helper |
| `tests/engine/test_executor_error_e2e_mock.py` (new) | 3 | Full chain end-to-end mock: spawn failure / stream is_error / payload round-trip |
| `frontend/src/stores/__tests__/workflowStore.errorEvents.test.ts` | 14 | handleWorkflowError / pushExecutorError / pushApiRetry / pushStatusUpdate |
| `frontend/src/components/conversation/__tests__/executorErrorHelpers.test.ts` | 25 | Headline formatting / retry_attempt gate / stderr gate / api_retry text / status text |

### Manual e2e (documented, requires server + frontend)

Deliberately not automated (requires real API tokens + interactive browser):

1. Set bad `ANTHROPIC_BASE_URL=http://nonexistent.invalid` in `.env`
2. Start `uvicorn server.main:app` + frontend dev server
3. Open browser, run `ask_user_demo` workflow
4. Verify red toast appears with `[spawn]` tag + stderr_tail preview
5. Verify `ExecutorErrorBanner` renders inline with phase / exit_code / stderr_tail
6. CLI parity: `harness run ask_user_demo` → stderr shows same fields

## Out of scope (Phase 3)

- CliProfile abstraction for opencode/codex
- User-defined CLI backends via `.harness/cli_profiles/<name>.py`
- Profile-aware env overlay (HARNESS_<NAME>_CLI / HARNESS_<NAME>_ENV_*)

## Commit SHAs

- `74a6a9a` — P2-T1: ErrorEvent dataclass + ExecutorError
- `a7a8f24` — P2-T2: agent.executor_error critical in bus.py
- `6071373` — P2-T3: ClaudeCodeExecutor 5-phase error encapsulation
- `f7e5c3c` — P2-T4: translator split + api_retry/status
- `ff5d4b6` — P2-T5: node_factory ExecutorError propagation
- `a0d9077` — P2-T6: server workflow.error enriched payload
- `500f826` — P2-T7: cli_runner server-parity payload via shared helper
- `cc337f0` — P2-T8: frontend store + handlers for new events
- `705da8c` — P2-T9: frontend inline banner + live badges
- `<this commit>` — P2-T10: e2e mock test + release note

## Verification results

- `python -m pytest tests/engine/ tests/server/test_runner_error_payload.py tests/test_executor_error_event.py tests/test_bus_critical_types.py tests/test_node_factory_prompt_dispatch.py tests/translator/` → 279 passed
- `vitest run` (frontend) → 306/307 passed (1 pre-existing benchmark flake, passes in isolation)
- `tests/engine/test_executor_error_e2e_mock.py` → 3 e2e mock cases covering spawn / stream / round-trip paths
