"""P2-T5: node_factory ExecutorError propagation acceptance tests.

Locks the contract that when an executor raises ExecutorError, node_factory:

  - DOES NOT re-emit ``agent.executor_error`` (emit-uniqueness, ADR D2)
  - DOES emit ``node.failed`` enriched with executor-side fields
    (stderr_tail / executor_phase / executor / exit_code / executor_extra)
    so the frontend can render the failure context from a single event
  - DOES preserve node-level context (tool_calls_before_failure / io_data)
    on the same node.failed event
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from harness.engine.error_event import ErrorEvent, ExecutorError
from harness.engine.node_factory import make_node_func


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
        self.workflow_id = "wf-1"
        self._workflow_name = "test-wf"
        self.request_limit = None
        self.envelope = None
        self.agent_io: dict[str, dict] = {}  # node_factory writes here
        self.todo_states: dict[str, list] = {}
        self.tool_registry = MagicMock()
        self.tool_registry.expand_globs.side_effect = lambda names, strict=False: names
        self.micro_factory.tool_registry.get_tool_info.return_value = []
        self.micro_factory.build_node_prompt.return_value = "test context"
        self.micro_factory.create.return_value = MagicMock()


class _StubParsed:
    def __init__(self, prompt="body", tools=None, model=None, retries=3):
        self.prompt = prompt
        self.tools = tools or []
        self.model = model
        self.retries = retries


class _StubAgentDef:
    def __init__(self, name="agent", executor="claude-code",
                 tools=None, after=None, on_pass=None, on_fail=None,
                 result_type=None, eval=None):
        self.name = name
        self.executor = executor
        self.tools = tools or []
        self.model = None
        self.retries = 3
        self.after = after if after is not None else []
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.result_type = result_type
        self.eval = eval
        self.has_conditional_edges = bool(on_pass or on_fail)


class _RecordingBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def _build_executor_error(phase="spawn", **ev_kwargs):
    defaults = dict(
        workflow_id="wf-1",
        node_id="agent",
        agent_name="agent",
        executor="claude-code",
        phase=phase,
        error_type="ClaudeSubprocessExit",
        error_message="claude exited code=1",
        stderr_tail="Error: ANTHROPIC_AUTH_TOKEN invalid\n",
        exit_code=1,
    )
    defaults.update(ev_kwargs)
    ev = ErrorEvent(**defaults)
    return ExecutorError(ev.error_message, ev)


_INITIAL_STATE = {
    "node_invocation_counts": {},
    "iteration_counts": {},
    "outputs": {},
    "inputs": {},
    "metadata": {},
    "errors": {},
}


@contextmanager
def _failing_executor_patches(bus, agent_def, fail_with, *, executor_tool_calls=None):
    """Yield a node_func whose executor.run raises ``fail_with``.

    Patches must be active during node_func invocation (not just during
    construction) because node_factory captures make_executor /
    execute_with_retry by name at module scope.

    executor_tool_calls: optional list to populate executor.tool_calls
        (defaults to empty).
    """
    failing_executor = MagicMock()
    failing_executor.tool_calls = list(executor_tool_calls or [])
    failing_executor.run = MagicMock(side_effect=fail_with)
    failing_executor.record_usage = MagicMock()
    failing_executor.get_last_request_usage.return_value = {
        "last_input": 0, "last_output": 0, "last_cache_hit": 0,
    }

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
        "harness.engine.node_factory.safe_emit",
        side_effect=lambda b, t, p: b.emit(t, p),
    ):
        yield make_node_func(
            builder=builder,
            agent_def=agent_def,
            parsed=_StubParsed(prompt="# Agent\n\nDo thing."),
            dep_map={agent_def.name: []},
            workflow_dir="/tmp",
        )


# ---------------------------------------------------------------------------
# Non-root agent: ExecutorError swallowed (returned in STATE_ERRORS) so
# on_fail conditional edges can recover. node.failed is still emitted.
# ---------------------------------------------------------------------------


def test_executor_error_does_not_re_emit_executor_error_event():
    """Non-root agent ExecutorError → node_factory emits node.failed ONLY.
    agent.executor_error was already emitted by the executor (P2-T3);
    re-emitting here would double-count failures on the frontend."""
    bus = _RecordingBus()
    err = _build_executor_error()
    agent_def = _StubAgentDef(name="greeter", after=["setup"])  # non-root

    with _failing_executor_patches(bus, agent_def, err) as node_func:
        _run(node_func(dict(_INITIAL_STATE)))

    emitted_types = [t for (t, _) in bus.events]
    assert "node.failed" in emitted_types, "node.failed must still emit (lifecycle owner)"
    assert "agent.executor_error" not in emitted_types, (
        "node_factory MUST NOT re-emit agent.executor_error — emit-uniqueness "
        "invariant (ADR Decision 2). Executor already emitted it."
    )


def test_executor_error_enriches_node_failed_with_executor_context():
    """The node.failed payload must carry executor-side fields
    (stderr_tail / executor_phase / executor / exit_code / executor_extra)
    so the frontend can render the failure cause from a single event.

    Note: build_node_failed_payload flattens ``extra`` into the payload
    top-level (not nested under an ``extra`` key) — verified at
    harness/engine/node_phases.py:143."""
    bus = _RecordingBus()
    err = _build_executor_error(
        phase="spawn",
        stderr_tail="Error: invalid token",
        exit_code=2,
        extra={"api_error_status": 401},
    )
    agent_def = _StubAgentDef(name="greeter", after=["setup"])

    with _failing_executor_patches(bus, agent_def, err) as node_func:
        _run(node_func(dict(_INITIAL_STATE)))

    node_failed_events = [p for (t, p) in bus.events if t == "node.failed"]
    assert len(node_failed_events) == 1
    payload = node_failed_events[0]
    # error_type upgraded from ErrorEvent (more specific than "ExecutorError")
    assert payload["error_type"] == "ClaudeSubprocessExit"
    # Extra fields flattened to top-level
    assert payload.get("stderr_tail") == "Error: invalid token"
    assert payload.get("executor_phase") == "spawn"
    assert payload.get("executor") == "claude-code"
    assert payload.get("exit_code") == 2
    assert payload.get("executor_extra") == {"api_error_status": 401}


def test_executor_error_preserves_node_level_context():
    """tool_calls_before_failure + io_data (node-level) must still appear
    alongside executor-side fields on the same node.failed event."""
    bus = _RecordingBus()
    err = _build_executor_error()
    agent_def = _StubAgentDef(name="greeter", after=["setup"])
    tool_calls = [
        {"tool_name": "Bash", "tool_args": {"cmd": "ls"}, "tool_call_id": "x"},
    ]

    with _failing_executor_patches(
        bus, agent_def, err, executor_tool_calls=tool_calls,
    ) as node_func:
        _run(node_func(dict(_INITIAL_STATE)))

    node_failed_events = [p for (t, p) in bus.events if t == "node.failed"]
    assert len(node_failed_events) == 1
    payload = node_failed_events[0]
    assert "tool_calls_before_failure" in payload, (
        "node-level context (tool_calls) must survive alongside executor fields"
    )
    assert "io_data" in payload
    # Executor enrichment coexists on the same flattened payload
    assert "stderr_tail" in payload
    assert "executor_phase" in payload


# ---------------------------------------------------------------------------
# Root agent: ExecutorError re-raises (LangGraph terminates the workflow).
# node.failed is still emitted BEFORE the re-raise.
# ---------------------------------------------------------------------------


def test_root_agent_executor_error_re_raises_after_emitting_node_failed():
    """Root agent (after=[]) ExecutorError must re-raise so LangGraph
    terminates — root failure = setup failure = no point continuing.
    node.failed is still emitted first so the frontend sees the failure."""
    bus = _RecordingBus()
    err = _build_executor_error()
    agent_def = _StubAgentDef(name="setup", after=[])  # root agent

    with _failing_executor_patches(bus, agent_def, err) as node_func:
        with pytest.raises(ExecutorError):
            _run(node_func(dict(_INITIAL_STATE)))

    # node.failed was emitted before the re-raise
    assert any(t == "node.failed" for (t, _) in bus.events)
    # agent.executor_error still not re-emitted
    assert not any(t == "agent.executor_error" for (t, _) in bus.events)


# ---------------------------------------------------------------------------
# Non-ExecutorError (surprise exception) — original behavior unchanged.
# ---------------------------------------------------------------------------


def test_non_executor_error_behavior_unchanged():
    """A plain RuntimeError (not from executor's ErrorEvent flow) MUST
    still trigger the original node.failed emit WITHOUT the executor
    enrichment fields. Locks P2-T5 as a pure superset, not a rewrite."""
    bus = _RecordingBus()
    surprise = RuntimeError("totally unexpected")
    agent_def = _StubAgentDef(name="agent", after=["setup"])

    with _failing_executor_patches(bus, agent_def, surprise) as node_func:
        _run(node_func(dict(_INITIAL_STATE)))

    node_failed_events = [p for (t, p) in bus.events if t == "node.failed"]
    assert len(node_failed_events) == 1
    payload = node_failed_events[0]
    # No executor enrichment — original behavior
    assert "stderr_tail" not in payload
    assert "executor_phase" not in payload
    assert "executor_extra" not in payload
    # error_type stays as RuntimeError class name (legacy behavior)
    assert payload["error_type"] == "RuntimeError"
