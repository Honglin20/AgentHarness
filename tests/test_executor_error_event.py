"""P2-T1: ErrorEvent dataclass + ExecutorError exception acceptance tests.

Locks the canonical error contract documented in
``harness/engine/error_event.py``:

  - ErrorEvent fields / defaults / types
  - to_payload / from_payload round-trip preserves all fields
  - ExecutorError carries error_event through the call stack
  - node_factory can identify ExecutorError via isinstance without
    re-emitting (re-emit happens at executor boundary, not here)
"""
from __future__ import annotations

import pickle
import time

import pytest

from harness.engine.error_event import ErrorEvent, ExecutorError


def _sample_event(**overrides):
    """Build an ErrorEvent with sane defaults; tests override fields."""
    defaults = dict(
        workflow_id="wf-1",
        node_id="greeter",
        agent_name="greeter",
        executor="claude-code",
        phase="spawn",
        error_type="RuntimeError",
        error_message="claude exited code=1",
        stderr_tail="Error: ANTHROPIC_AUTH_TOKEN invalid\n",
        exit_code=1,
        timed_out=False,
        retry_attempt=1,
    )
    defaults.update(overrides)
    return ErrorEvent(**defaults)


# ---------------------------------------------------------------------------
# ErrorEvent field semantics
# ---------------------------------------------------------------------------


def test_error_event_required_fields():
    """All required positional fields must be present at construction."""
    ev = ErrorEvent(
        workflow_id="w", node_id="n", agent_name="n",
        executor="claude-code", phase="spawn",
        error_type="RuntimeError", error_message="boom",
    )
    assert ev.stderr_tail is None
    assert ev.exit_code is None
    assert ev.timed_out is False
    assert ev.retry_attempt is None
    assert ev.extra == {}
    assert ev.ts > 0  # default_factory populated


def test_error_event_ts_defaults_to_construction_time():
    """ts is auto-populated; tests can override for determinism."""
    t0 = time.time()
    ev = _sample_event()
    t1 = time.time()
    assert t0 <= ev.ts <= t1


def test_error_event_extra_defaults_to_empty_dict_independent_per_instance():
    """mutable default must not leak across instances (dataclass field trap)."""
    ev1 = _sample_event()
    ev2 = _sample_event()
    ev1.extra["k"] = "v"
    assert ev2.extra == {}, "extra dict shared across instances — dataclass trap"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_to_payload_omits_none_optionals():
    """None optional fields should NOT appear in the payload — sinks rely
    on absence to render conditionally (frontend hides stderr_tail block
    when the key is missing). timed_out is the exception: always present
    (boolean explicit, distinguishing False from missing)."""
    ev = _sample_event(stderr_tail=None, exit_code=None, retry_attempt=None,
                       timed_out=False, extra={})
    payload = ev.to_payload()
    for absent_key in ("stderr_tail", "exit_code", "retry_attempt", "extra"):
        assert absent_key not in payload, f"{absent_key} should be omitted when empty"
    assert payload["timed_out"] is False  # always present (boolean explicit)


def test_to_payload_includes_all_populated_fields():
    ev = _sample_event(extra={"api_error_status": 429})
    payload = ev.to_payload()
    assert payload["stderr_tail"].startswith("Error:")
    assert payload["exit_code"] == 1
    assert payload["retry_attempt"] == 1
    assert payload["timed_out"] is False
    assert payload["extra"] == {"api_error_status": 429}
    assert payload["executor"] == "claude-code"
    assert payload["phase"] == "spawn"
    assert "ts" in payload


def test_from_payload_reconstructs_all_fields():
    """to_payload → from_payload is a lossless round-trip."""
    original = _sample_event(extra={"k": "v"})
    roundtripped = ErrorEvent.from_payload(original.to_payload())
    assert roundtripped == original


def test_from_payload_tolerates_missing_optionals():
    """Reconstruction from a sparse payload (e.g. minimal WS message)
    should default missing fields safely, not raise."""
    sparse = {
        "workflow_id": "w",
        "executor": "claude-code",
        "phase": "spawn",
        "error_type": "RuntimeError",
        "error_message": "boom",
    }
    ev = ErrorEvent.from_payload(sparse)
    assert ev.node_id is None
    assert ev.agent_name is None
    assert ev.stderr_tail is None
    assert ev.timed_out is False
    assert ev.extra == {}


def test_to_payload_returns_fresh_dict_each_call():
    """to_payload must return a NEW dict each call so callers can mutate
    (e.g. sinks adding routing metadata) without polluting the source event.
    Mutable-default bug magnet — lock it down."""
    ev = _sample_event(extra={"k": "v"})
    p1 = ev.to_payload()
    p2 = ev.to_payload()
    assert p1 is not p2, "to_payload returned the same dict object — aliasing bug"
    p1["extra"]["injected"] = True
    assert "injected" not in p2["extra"], "extra dict aliased across calls"
    assert "injected" not in ev.extra, "extra mutation backflowed to source event"


# ---------------------------------------------------------------------------
# ExecutorError exception
# ---------------------------------------------------------------------------


def test_executor_error_carries_error_event():
    """node_factory's except clause can access error_event without parsing."""
    ev = _sample_event()
    err = ExecutorError("boom", ev)
    assert isinstance(err, RuntimeError)
    assert err.error_event is ev
    assert str(err) == "boom"


def test_executor_error_isinstance_distinguishes_from_plain_runtime_error():
    """The dedicated exception type lets node_factory branch:

        if isinstance(e, ExecutorError):
            # already emitted, route only
        else:
            # surprise exception, emit fresh
    """
    ev = _sample_event()
    assert isinstance(ExecutorError("x", ev), ExecutorError)
    assert not isinstance(RuntimeError("plain"), ExecutorError)


def test_executor_error_pickle_round_trip():
    """Picklability matters for tests + potential multiprocessing sinks.
    __reduce__ must reconstruct losslessly."""
    ev = _sample_event()
    err = ExecutorError("boom", ev)
    restored = pickle.loads(pickle.dumps(err))
    assert isinstance(restored, ExecutorError)
    assert restored.error_event == ev
    assert str(restored) == "boom"


# ---------------------------------------------------------------------------
# Phase literal contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase", [
    "spawn", "stream", "result_parse", "schema_validate", "timeout", "runtime",
])
def test_canonical_phases_accepted(phase):
    """The documented phase set must all construct cleanly. Adding a new
    phase = updating ExecutorPhase Literal + this test."""
    ev = _sample_event(phase=phase)
    assert ev.phase == phase


def test_non_canonical_phase_not_validated_at_runtime():
    """dataclass does not enforce Literal at runtime (Python limitation) —
    callers must guard. This test documents the gap so future hardening
    (pydantic dataclass / __post_init__) is deliberate."""
    ev = _sample_event(phase="made-up-phase")
    # No exception raised — Literal is type-hint only
    assert ev.phase == "made-up-phase"
