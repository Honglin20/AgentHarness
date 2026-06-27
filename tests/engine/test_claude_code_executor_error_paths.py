"""P2-T3: ClaudeCodeExecutor error encapsulation acceptance tests.

Locks the contract that every error phase (spawn / stream / result_parse /
schema_validate / timeout) emits exactly one ``agent.executor_error`` event
to the bus + raises ``ExecutorError`` carrying the same ErrorEvent. The
translator stops emitting node.failed for result.is_error so the executor
is the sole emit point (ADR Decision 2 invariant).
"""
from __future__ import annotations

import asyncio
import json
from typing import Sequence

import pytest
from pydantic import BaseModel

from harness.core.agent import Agent
from harness.engine.cli_profile import CliRunResult, CliSpawnConfig
from harness.engine._result_extractor import SchemaValidationError
from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.error_event import ErrorEvent, ExecutorError
from harness.types import AgentResult


class _Summary(BaseModel):
    summary: str
    count: int


class FakeBus:
    """Captures all emit calls for assertions."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def make_fake_run_claude(
    lines: Sequence[str] = (),
    *,
    exit_code: int = 0,
    stderr: str = "",
    timed_out: bool = False,
):
    async def fake(cfg: CliSpawnConfig, profile=None, on_line=None, *, timeout=None):
        if on_line is not None:
            for line in lines:
                await on_line(line)
        return CliRunResult(
            exit_code=exit_code, stderr=stderr, timed_out=timed_out,
        )
    return fake


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_executor(*, bus: FakeBus, agent_def=None, timeout_s=None):
    if agent_def is None:
        agent_def = Agent("a")  # default result_type=AgentResult
    return ClaudeCodeExecutor(
        agent_def=agent_def,
        deps=None,
        event_bus=bus,
        workflow_id="wf-1",
        node_id="greeter",
        agent_name="greeter",
        enable_mcp=False,
        timeout_s=timeout_s,
    )


# ---------------------------------------------------------------------------
# spawn phase: exit_code != 0
# ---------------------------------------------------------------------------


def test_spawn_phase_nonzero_exit_emits_and_raises(monkeypatch):
    """exit_code != 0 → emit agent.executor_error (phase=spawn) + raise
    ExecutorError. The payload must carry stderr_tail + exit_code."""
    bus = FakeBus()
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(exit_code=1, stderr="Error: invalid token\n"),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    err = exc_info.value
    assert err.error_event.phase == "spawn"
    assert err.error_event.exit_code == 1
    assert "invalid token" in err.error_event.stderr_tail
    # Emit-uniqueness: exactly one agent.executor_error event on the bus
    executor_errors = [e for e in bus.events if e[0] == "agent.executor_error"]
    assert len(executor_errors) == 1
    assert executor_errors[0][1]["phase"] == "spawn"
    assert executor_errors[0][1]["exit_code"] == 1


# ---------------------------------------------------------------------------
# timeout phase
# ---------------------------------------------------------------------------


def test_timeout_phase_emits_with_timed_out_true(monkeypatch):
    """timed_out=True → phase=timeout, timed_out=True in payload. Distinct
    from exit_code!=0 to disambiguate SIGTERM-from-us vs exit-from-cli."""
    bus = FakeBus()
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(timed_out=True, exit_code=-1),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    assert exc_info.value.error_event.phase == "timeout"
    assert exc_info.value.error_event.timed_out is True


# ---------------------------------------------------------------------------
# stream phase: result.is_error=true
# ---------------------------------------------------------------------------


def test_stream_phase_is_error_emits_with_api_error_status(monkeypatch):
    """result.is_error=true → phase=stream. Translator no longer emits
    node.failed (P2-T4) — executor owns this emit. api_error_status must
    surface in extra for retry classification (429 vs 500)."""
    bus = FakeBus()
    lines = [
        json.dumps({
            "type": "result",
            "is_error": True,
            "api_error_status": 429,
            "duration_ms": 100,
            "result": "rate limited",
            "usage": {},
        }),
    ]
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    err = exc_info.value
    assert err.error_event.phase == "stream"
    assert err.error_event.extra.get("api_error_status") == 429


def test_stream_phase_error_message_includes_claude_result_description(monkeypatch):
    """When result.result contains claude's error description, the emitted
    error_message must surface it so the frontend can show WHY the stream
    failed without digging into stderr."""
    bus = FakeBus()
    lines = [
        json.dumps({
            "type": "result",
            "is_error": True,
            "api_error_status": 500,
            "duration_ms": 100,
            "result": "Internal server error: prompt cache miss",
            "usage": {},
        }),
    ]
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    err = exc_info.value
    assert "Internal server error" in err.error_event.error_message
    assert err.error_event.extra.get("api_error_result") == "Internal server error: prompt cache miss"


def test_stream_phase_no_result_description_falls_back_to_api_status(monkeypatch):
    """If claude emits is_error without a useful result.result, the message
    falls back to api_error_status instead of being generic."""
    bus = FakeBus()
    lines = [
        json.dumps({
            "type": "result", "is_error": True,
            "api_error_status": 503, "duration_ms": 100,
            "result": None, "usage": {},
        }),
    ]
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    assert "api_error_status=503" in exc_info.value.error_event.error_message


def test_stream_phase_no_node_failed_emitted_from_translator(monkeypatch):
    """P2-T4 contract: when result.is_error=true, the translator MUST NOT
    emit node.failed — the executor owns the emit (emit-uniqueness). This
    test will be enforced fully after P2-T4 lands; for now we verify the
    executor emits exactly one executor_error and the executor does not
    double-emit on its own."""
    bus = FakeBus()
    lines = [
        json.dumps({
            "type": "result", "is_error": True, "duration_ms": 100,
            "result": "boom", "usage": {},
        }),
    ]
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError):
        _run(ex.run("ctx"))
    executor_errors = [e for e in bus.events if e[0] == "agent.executor_error"]
    assert len(executor_errors) == 1, "executor must emit exactly one event"


# ---------------------------------------------------------------------------
# result_parse phase: claude exit 0 but no result event
# ---------------------------------------------------------------------------


def test_result_parse_phase_no_result_event_emits(monkeypatch):
    """claude exits 0 but emits no result event → phase=result_parse."""
    bus = FakeBus()
    # empty stdout — no result line
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines=(), exit_code=0),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    assert exc_info.value.error_event.phase == "result_parse"


# ---------------------------------------------------------------------------
# schema_validate phase
# ---------------------------------------------------------------------------


def test_schema_validate_phase_wraps_schema_validation_error(monkeypatch):
    """SchemaValidationError from extract_and_validate → phase=schema_validate.
    Lets execute_with_retry drive schema-fail retries uniformly."""
    bus = FakeBus()
    lines = [
        json.dumps({
            "type": "result", "is_error": False, "duration_ms": 100,
            "result": "not valid json", "usage": {},
        }),
    ]
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(lines),
    )
    # Provide a custom result_type so _extract_and_validate_result invokes
    # extract_and_validate (which will fail on "not valid json")
    agent_def = Agent("a", result_type=_Summary)
    ex = _make_executor(bus=bus, agent_def=agent_def)
    with pytest.raises(ExecutorError) as exc_info:
        _run(ex.run("ctx"))
    err = exc_info.value
    assert err.error_event.phase == "schema_validate"
    assert err.error_event.error_type == "SchemaValidationError"
    assert err.error_event.extra.get("raw_result_text_len") == len("not valid json")


# ---------------------------------------------------------------------------
# Emit-uniqueness invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase_setup", [
    ("spawn", {"exit_code": 1, "stderr": "boom"}),
    ("timeout", {"timed_out": True, "exit_code": -1}),
])
def test_exactly_one_executor_error_event_per_failure(monkeypatch, phase_setup):
    """Across every phase, the bus must contain exactly 1
    agent.executor_error event. Duplicate emits would double-count failures
    on the frontend and break the ADR Decision 2 invariant."""
    bus = FakeBus()
    phase, kwargs = phase_setup
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(**kwargs),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError):
        _run(ex.run("ctx"))
    executor_errors = [e for e in bus.events if e[0] == "agent.executor_error"]
    assert len(executor_errors) == 1


def test_no_bus_no_emit_but_still_raises(monkeypatch):
    """If bus is None (unit test / CI), executor still raises ExecutorError
    so the caller's retry layer can route. Emit is skipped, not crashed."""
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(exit_code=1, stderr="boom"),
    )
    ex = ClaudeCodeExecutor(
        agent_def=Agent("a"), deps=None, event_bus=None,
        workflow_id="w", node_id="n", agent_name="a", enable_mcp=False,
    )
    with pytest.raises(ExecutorError):
        _run(ex.run("ctx"))


# ---------------------------------------------------------------------------
# ErrorEvent field sanity on emitted payloads
# ---------------------------------------------------------------------------


def test_emitted_payload_round_trips_through_error_event(monkeypatch):
    """The emitted payload must be consumable via ErrorEvent.from_payload
    so the frontend / replay path / sinks all see the same shape."""
    bus = FakeBus()
    monkeypatch.setattr(
        "harness.engine.claude_code_executor.run_cli",
        make_fake_run_claude(exit_code=2, stderr="Error: rate limit\n"),
    )
    ex = _make_executor(bus=bus)
    with pytest.raises(ExecutorError):
        _run(ex.run("ctx"))
    event_type, payload = bus.events[0]
    assert event_type == "agent.executor_error"
    # Round-trip
    reconstructed = ErrorEvent.from_payload(payload)
    assert reconstructed.executor == "claude-code"
    assert reconstructed.phase == "spawn"
    assert reconstructed.exit_code == 2
    assert "rate limit" in reconstructed.stderr_tail
