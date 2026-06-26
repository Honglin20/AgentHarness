"""Executor error event contract + ExecutorError exception base (P2-T1).

Defines the canonical error shape emitted by all executors (LLMExecutor /
ClaudeCodeExecutor / future CliExecutorBase subclasses) so the rest of the
system (node_factory retry / server runner / cli_runner / frontend) can
consume a single rich payload instead of stringified exceptions.

Emit-uniqueness contract (ADR Decision 2 invariant):
  Each error is emitted **exactly once** at its source. Downstream layers
  consume the ExecutorError exception via ``except ExecutorError`` and MUST
  NOT re-emit ``agent.executor_error`` — they propagate / re-raise / route
  based on ``error_event`` instead. The translator (``stream_json.py``)
  stops emitting ``node.failed`` for ``result.is_error=true`` so the
  executor remains the sole emit point for stream-phase errors.

Why a dataclass + exception pair (instead of just an exception):
  - The dataclass is the wire payload — emitted to the bus and consumed by
    the frontend via WS / by the CLI via stderr.
  - The exception carries the same payload through the Python call stack
    so node_factory / execute_with_retry can route without re-serializing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


#: Canonical lifecycle phases an executor error can originate from.
#:
#: Adding a new phase is a framework-level change — frontend / sinks expect
#: these strings to render phase labels. Keep the set small + generic.
ExecutorPhase = Literal[
    "spawn",           # subprocess failed to start / exited non-zero
    "stream",          # stream-json indicated is_error, or stream parse failed
    "result_parse",    # claude exited 0 but emitted no parseable result event
    "schema_validate", # result text did not match agent's result_type schema
    "timeout",         # wall-clock timeout fired
    "runtime",         # anything else (catch-all; prefer a more specific phase)
]


@dataclass
class ErrorEvent:
    """Canonical executor error payload.

    Emitted as ``agent.executor_error`` on the bus (CRITICAL_EVENT_TYPES —
    never FIFO-evicted). Mirrored on ``ExecutorError.error_event`` so the
    Python call stack carries the same context.

    Field semantics:
      workflow_id    Run the error belongs to (always present).
      node_id        Agent node name, or None for workflow-level errors.
      agent_name     Same as node_id for now; kept distinct for future
                     sub-agent granularity.
      executor       Backend that produced the error ("pydantic-ai" /
                     "claude-code" / ...).
      phase          Lifecycle phase — see ``ExecutorPhase``.
      error_type     Exception class name (e.g. "RuntimeError", "SchemaValidationError").
      error_message  ``str(exception)`` — short, human-readable.
      stderr_tail    CLI-backend-specific: last ~500 chars of subprocess stderr.
                     None for in-process executors.
      exit_code      CLI-backend-specific: subprocess exit code. None for
                     in-process executors or pre-spawn failures.
      timed_out      True iff a wall-clock timeout fired (distinct from
                     exit_code to disambiguate SIGTERM-from-us vs exit-from-cli).
      retry_attempt  1-indexed attempt number when this error fired (None
                     if executor does not track attempts).
      ts             Unix epoch seconds (float). Defaults to construction time.
      extra          Backend-specific extension fields (e.g. api_error_status
                     for Anthropic 429/500). Frontends render best-effort.
    """

    workflow_id: str
    node_id: str | None
    agent_name: str | None
    executor: str
    phase: str
    error_type: str
    error_message: str
    stderr_tail: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    retry_attempt: int | None = None
    ts: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a bus-emit / WS-send / JSON-storable dict.

        Optional fields (``stderr_tail`` / ``exit_code`` / ``retry_attempt``
        / ``extra``) are omitted when unset so sinks can detect absence
        (frontend hides the stderr block when the key is missing).
        ``timed_out`` is always present (boolean explicit): receivers should
        be able to distinguish "definitely did not time out" from "field
        was missing" without a three-state enum.
        """
        payload: dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "executor": self.executor,
            "phase": self.phase,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "timed_out": self.timed_out,
            "ts": self.ts,
        }
        if self.stderr_tail is not None:
            payload["stderr_tail"] = self.stderr_tail
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.retry_attempt is not None:
            payload["retry_attempt"] = self.retry_attempt
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ErrorEvent":
        """Reconstruct from a bus/WS payload dict (inverse of to_payload).

        Tolerant: missing optional keys default to None / empty / False.
        Used by replay paths + tests that simulate round-tripping.
        """
        return cls(
            workflow_id=payload["workflow_id"],
            node_id=payload.get("node_id"),
            agent_name=payload.get("agent_name"),
            executor=payload["executor"],
            phase=payload["phase"],
            error_type=payload["error_type"],
            error_message=payload["error_message"],
            stderr_tail=payload.get("stderr_tail"),
            exit_code=payload.get("exit_code"),
            timed_out=bool(payload.get("timed_out", False)),
            retry_attempt=payload.get("retry_attempt"),
            ts=float(payload.get("ts", time.time())),
            extra=dict(payload.get("extra") or {}),
        )


class ExecutorError(RuntimeError):
    """Exception raised by executors after emitting the canonical ErrorEvent.

    Contract:
      - Executors construct + emit ``ErrorEvent`` to the bus FIRST.
      - Then raise ``ExecutorError(message, error_event)`` so the call
        stack carries the same context.
      - ``node_factory.execute_with_retry`` catches ``ExecutorError`` to
        drive retry / classify-failure logic WITHOUT re-emitting
        ``agent.executor_error`` (the executor already did).
      - Other exception types propagate unchanged (treated as bugs).

    Why a dedicated exception (not just RuntimeError):
      Lets ``node_factory``'s except clause distinguish "executor already
      emitted the canonical event" from "this is some other surprise
      exception that needs node_factory to emit on its own". Re-emitting
      would double-count errors on the frontend.
    """

    def __init__(self, message: str, error_event: ErrorEvent):
        super().__init__(message)
        self.error_event = error_event

    def __reduce__(self):  # pragma: no cover — pickle support for tests
        return (self.__class__, (str(self), self.error_event))
