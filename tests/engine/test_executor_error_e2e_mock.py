"""P2-T10: end-to-end mock test for the unified error flow.

Single-process integration test covering the full P2-T1..T9 path WITHOUT
spawning real claude -p:

  1. ClaudeCodeExecutor.run() detects a phase failure (mocked via fake
     run_claude that exits non-zero with stderr) → emits agent.executor_error
     (critical) + raises ExecutorError (P2-T3)
  2. node_factory except clause catches ExecutorError, emits node.failed
     enriched with executor-side fields WITHOUT re-emitting executor_error
     (P2-T5 emit-uniqueness)
  3. workflow.error payload built by build_workflow_error_payload surfaces
     stderr_tail / phase / executor / failed_node (P2-T6/T7 contract)

This locks the entire chain in a single test so a regression anywhere
in the path fails loudly. Real subprocess e2e (claude -p with bad env)
remains a manual smoke step documented in the release note.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from harness.engine.cli_profile import CliRunResult, CliSpawnConfig
from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.error_event import (
    ErrorEvent,
    ExecutorError,
    build_workflow_error_payload,
)
from harness.engine.node_factory import make_node_func
from harness.core.agent import Agent


class _RecordingBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.buffer: list[tuple[str, dict]] = []  # mirrors real Bus.buffer

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))
        self.buffer.append((event_type, payload))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _StubBuilder:
    def __init__(self):
        self.micro_factory = MagicMock()
        self.event_bus = None
        self.max_iterations = 5
        self.workflow_id = "wf-e2e"
        self._workflow_name = "e2e-wf"
        self.request_limit = None
        self.envelope = None
        self.agent_io: dict[str, dict] = {}
        self.todo_states: dict[str, list] = {}
        self.tool_registry = MagicMock()
        self.tool_registry.expand_globs.side_effect = lambda names, strict=False: names
        self.micro_factory.tool_registry.get_tool_info.return_value = []
        self.micro_factory.build_node_prompt.return_value = "ctx"
        self.micro_factory.create.return_value = MagicMock()


class _StubParsed:
    def __init__(self):
        self.prompt = "# Agent\n\nDo thing."
        self.tools = []
        self.model = None
        self.retries = 3


class _StubAgentDef:
    def __init__(self, name="setup", executor="claude-code", after=None):
        self.name = name
        self.executor = executor
        self.tools = []
        self.model = None
        self.retries = 3
        self.after = after if after is not None else []
        self.on_pass = None
        self.on_fail = None
        self.result_type = None
        self.eval = None
        self.has_conditional_edges = False


def test_e2e_unified_error_flow_claude_code_spawn_failure():
    """Mock claude -p exits 1 → agent.executor_error emitted (critical,
    P2-T2) → ExecutorError raised (P2-T3) → node_factory catches and
    emits node.failed enriched (P2-T5, no re-emit of executor_error) →
    build_workflow_error_payload surfaces all fields (P2-T6/T7)."""

    bus = _RecordingBus()

    # Mock run_claude to fail with exit_code=1 + stderr indicating the spawn
    # problem (simulates bad ANTHROPIC_BASE_URL).
    async def fake_run_claude(cfg, profile=None, on_line=None, *, timeout=None):
        return CliRunResult(
            exit_code=1,
            stderr="Error: ANTHROPIC_AUTH_TOKEN invalid\nConnection refused\n",
            timed_out=False,
        )

    failing_executor = ClaudeCodeExecutor(
        agent_def=Agent("setup"),
        deps=None,
        event_bus=bus,
        workflow_id="wf-e2e",
        node_id="setup",
        agent_name="setup",
        enable_mcp=False,
    )

    builder = _StubBuilder()
    builder.event_bus = bus

    async def _passthrough_retry(run_fn, **_kw):
        return await run_fn()

    with patch(
        "harness.engine.node_factory.make_executor",
        return_value=failing_executor,
    ), patch(
        "harness.engine.node_factory.execute_with_retry",
        side_effect=_passthrough_retry,
    ), patch(
        "harness.engine.claude_code_executor.run_cli",
        side_effect=fake_run_claude,
    ), patch(
        "harness.engine.node_factory.safe_emit",
        side_effect=lambda b, t, p: b.emit(t, p),
    ):
        node_func = make_node_func(
            builder=builder,
            agent_def=_StubAgentDef(name="setup", after=["bootstrap"]),  # non-root
            parsed=_StubParsed(),
            dep_map={"setup": []},
            workflow_dir="/tmp",
        )
        # Root agent would re-raise; non-root swallows so we can inspect events
        _run(node_func({
            "node_invocation_counts": {}, "iteration_counts": {},
            "outputs": {}, "inputs": {}, "metadata": {}, "errors": {},
        }))

    # ── Verify the canonical event chain ──────────────────────────────────
    emitted_types = [t for (t, _) in bus.events]

    # 1. agent.executor_error was emitted exactly once (critical, P2-T3)
    executor_errors = [p for (t, p) in bus.events if t == "agent.executor_error"]
    assert len(executor_errors) == 1, (
        f"executor must emit exactly 1 agent.executor_error; got {len(executor_errors)}"
    )
    ev_payload = executor_errors[0]
    assert ev_payload["phase"] == "spawn"
    assert ev_payload["executor"] == "claude-code"
    assert ev_payload["error_type"] == "ClaudeSubprocessExit"
    assert "ANTHROPIC_AUTH_TOKEN" in ev_payload["stderr_tail"]
    assert ev_payload["exit_code"] == 1

    # 2. node.failed was emitted with executor-enriched extra (P2-T5)
    node_faileds = [p for (t, p) in bus.events if t == "node.failed"]
    assert len(node_faileds) == 1
    nf_payload = node_faileds[0]
    assert nf_payload["error_type"] == "ClaudeSubprocessExit"  # upgraded from ErrorEvent
    assert nf_payload["stderr_tail"] == ev_payload["stderr_tail"]
    assert nf_payload["executor_phase"] == "spawn"
    assert nf_payload["executor"] == "claude-code"

    # 3. agent.executor_error was NOT re-emitted (emit-uniqueness invariant)
    assert emitted_types.count("agent.executor_error") == 1

    # 4. workflow.error payload built from the same context surfaces all fields
    snapshot = [{"name": "setup", "executor": "claude-code"}]
    workflow_payload = build_workflow_error_payload(
        workflow_id="wf-e2e", user_id="user-1",
        error=ExecutorError(
            "claude exited code=1",
            ErrorEvent.from_payload(ev_payload),
        ),
        agents_snapshot=snapshot,
        bus_buffer=bus.buffer,
        batch_id=None,
    )
    assert workflow_payload["phase"] == "spawn"
    assert workflow_payload["stderr_tail"] == ev_payload["stderr_tail"]
    assert workflow_payload["failed_node"] == "setup"
    assert workflow_payload["executor"] == "claude-code"


def test_e2e_unified_error_flow_stream_is_error():
    """Mock claude -p returns result.is_error=true → translator does NOT
    emit node.failed (P2-T4) → executor detects via _extract_pre_translate
    → emits agent.executor_error(phase=stream) + raises ExecutorError →
    node_factory catches and enriches."""

    bus = _RecordingBus()

    async def fake_run_claude(cfg, profile=None, on_line=None, *, timeout=None):
        # Stream a result event with is_error=true (rate limited)
        if on_line is not None:
            await on_line(json.dumps({
                "type": "result",
                "is_error": True,
                "api_error_status": 429,
                "duration_ms": 100,
                "result": "rate limited",
                "usage": {},
            }))
        return CliRunResult(exit_code=0, stderr="", timed_out=False)

    failing_executor = ClaudeCodeExecutor(
        agent_def=Agent("analyzer"),
        deps=None,
        event_bus=bus,
        workflow_id="wf-e2e",
        node_id="analyzer",
        agent_name="analyzer",
        enable_mcp=False,
    )

    builder = _StubBuilder()
    builder.event_bus = bus

    async def _passthrough_retry(run_fn, **_kw):
        return await run_fn()

    with patch(
        "harness.engine.node_factory.make_executor",
        return_value=failing_executor,
    ), patch(
        "harness.engine.node_factory.execute_with_retry",
        side_effect=_passthrough_retry,
    ), patch(
        "harness.engine.claude_code_executor.run_cli",
        side_effect=fake_run_claude,
    ), patch(
        "harness.engine.node_factory.safe_emit",
        side_effect=lambda b, t, p: b.emit(t, p),
    ):
        node_func = make_node_func(
            builder=builder,
            agent_def=_StubAgentDef(name="analyzer", after=["setup"]),
            parsed=_StubParsed(),
            dep_map={"analyzer": []},
            workflow_dir="/tmp",
        )
        _run(node_func({
            "node_invocation_counts": {}, "iteration_counts": {},
            "outputs": {}, "inputs": {}, "metadata": {}, "errors": {},
        }))

    # Stream phase: executor emits agent.executor_error with phase="stream"
    executor_errors = [p for (t, p) in bus.events if t == "agent.executor_error"]
    assert len(executor_errors) == 1
    assert executor_errors[0]["phase"] == "stream"
    assert "rate limited" in executor_errors[0]["error_message"]
    assert executor_errors[0]["extra"].get("api_error_status") == 429

    # Translator did NOT emit node.failed on is_error (P2-T4 contract) —
    # only node_factory's except clause does, once.
    node_faileds = [p for (t, p) in bus.events if t == "node.failed"]
    assert len(node_faileds) == 1
    assert node_faileds[0]["executor_phase"] == "stream"


def test_e2e_emitted_payload_round_trips_through_frontend_schema():
    """The emitted agent.executor_error payload must round-trip through
    ErrorEvent.from_payload so the frontend (which consumes the raw dict)
    can reconstruct the same context for inline rendering (P2-T9)."""
    bus = _RecordingBus()

    async def fake_run_claude(cfg, profile=None, on_line=None, *, timeout=None):
        return CliRunResult(exit_code=2, stderr="boom\n", timed_out=False)

    failing_executor = ClaudeCodeExecutor(
        agent_def=Agent("x"),
        deps=None, event_bus=bus,
        workflow_id="wf-rt", node_id="x", agent_name="x",
        enable_mcp=False,
    )
    with patch(
        "harness.engine.claude_code_executor.run_cli",
        side_effect=fake_run_claude,
    ):
        with pytest.raises(ExecutorError):
            _run(failing_executor.run("ctx"))

    # The bus received the to_payload() output. Round-trip it.
    event_type, payload = bus.events[-1]
    assert event_type == "agent.executor_error"
    reconstructed = ErrorEvent.from_payload(payload)
    # Fields the frontend toast / banner (P2-T8/T9) read are preserved
    assert reconstructed.executor == "claude-code"
    assert reconstructed.phase == "spawn"
    assert reconstructed.exit_code == 2
    assert reconstructed.stderr_tail == "boom\n"
    assert reconstructed.error_type == "ClaudeSubprocessExit"
