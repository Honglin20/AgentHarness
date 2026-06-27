"""Unit tests for InflightSidecarWriter (ADR D7 lifecycle).

Covers:
  - Full lifecycle (start → stream → tool → finalize)             [P2b-T17]
  - Debounced flush timing                                       [P2b-T18]
  - Atomic-rename safety (no partial files on write failure)     [P2b-T19]
  - Finalize clears streaming_text + fills output_result         [P2b-T20]
  - mark_failed preserves streaming_text + sets status=failed    [P2b-T21]
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.persistence.sidecar_writer import (
    InflightSidecarWriter,
    InflightWriterRegistry,
    attach_to_bus,
)


def _make_writer(tmp_path: Path, **kwargs) -> InflightSidecarWriter:
    """Factory with sensible defaults for tests."""
    defaults = {
        "run_id": "r1",
        "node_id": "scout",
        "iter_num": 1,
        "runs_dir": tmp_path,
        "debounce_ms": 500,
    }
    defaults.update(kwargs)
    return InflightSidecarWriter(**defaults)


# ── P2b-T17: full lifecycle ───────────────────────────────────────────


def test_full_lifecycle(tmp_path: Path):
    """on_started → text_delta × 3 → tool_call → tool_result → finalize.

    Final sidecar must reflect completed status, output_result set, all 3
    tool_calls present, streaming_text cleared, last_seq advanced.
    """
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="hello", system_prompt="sys", last_seq=100)
    w.on_text_delta("Hello ", 101)
    w.on_text_delta("world", 102)
    w.on_text_delta("!", 103)
    w.on_tool_call({"tool_name": "bash", "tool_args": {"cmd": "ls"}, "tool_call_id": "call_1"}, 104)
    w.on_tool_result("bash", "file1\nfile2", 105, tool_call_id="call_1")
    w.finalize(output_result={"summary": "done"}, last_seq=110)

    data = json.loads(w.path.read_text())
    assert data["status"] == "completed"
    assert data["output_result"] == {"summary": "done"}
    assert data["streaming_text"] == ""  # cleared on finalize
    assert data["last_seq"] == 110
    assert data["duration_ms"] is not None and data["duration_ms"] >= 0
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["tool_name"] == "bash"
    assert data["tool_calls"][0]["tool_result"] == "file1\nfile2"
    assert data["tool_calls"][0]["tool_call_id"] == "call_1"


def test_lifecycle_initial_on_started_writes_streaming_sidecar(tmp_path: Path):
    """node.started must immediately write a sidecar so refresh right after
    start sees status=streaming, not a missing file."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="hello", system_prompt="sys", last_seq=42)
    assert w.path.exists()
    data = json.loads(w.path.read_text())
    assert data["status"] == "streaming"
    assert data["streaming_text"] == ""
    assert data["last_seq"] == 42
    assert data["input_prompt"] == "hello"
    assert data["system_prompt"] == "sys"
    assert data["ended_at"] is None  # not finalized yet


# ── P2b-T18: debounced flush ─────────────────────────────────────────


def test_debounce_within_window(tmp_path: Path):
    """Multiple text_deltas within the debounce window flush only once."""
    w = _make_writer(tmp_path, debounce_ms=500)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    initial_flush_count = w.flush_count

    # Fire 5 deltas back-to-back (no time gap).
    for i in range(5):
        w.on_text_delta(f"chunk{i} ", 101 + i)

    # Should have flushed only for on_started; the 5 deltas within window
    # must NOT have each triggered a flush.
    assert w.flush_count == initial_flush_count


def test_debounce_across_window(tmp_path: Path):
    """After the debounce window passes, the next delta triggers a flush."""
    w = _make_writer(tmp_path, debounce_ms=10)  # short for fast test
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    after_started = w.flush_count

    # First delta within window — no flush yet.
    w.on_text_delta("first", 101)
    assert w.flush_count == after_started

    # Wait past the window.
    time.sleep(0.05)

    # Next delta triggers flush.
    w.on_text_delta("second", 102)
    assert w.flush_count == after_started + 1


def test_tool_call_bypasses_debounce(tmp_path: Path):
    """tool_call is a semantic boundary — flushes immediately even within window."""
    w = _make_writer(tmp_path, debounce_ms=10_000)  # long window
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    after_started = w.flush_count

    # text_delta within window — no flush.
    w.on_text_delta("x", 101)
    assert w.flush_count == after_started

    # tool_call immediately after — flushes despite the long window.
    w.on_tool_call({"tool_name": "X"}, 102)
    assert w.flush_count == after_started + 1


# ── P2b-T19: atomic rename — no partial files on crash ───────────────


def test_no_partial_file_when_save_fails(tmp_path: Path):
    """If save_iter_sidecar_safe fails (mocked), the writer must not leave
    a .tmp file behind — atomic_write_json (inside save_iter_sidecar_safe)
    cleans up tmp on failure."""
    w = _make_writer(tmp_path)

    with patch(
        "harness.persistence.sidecar_writer.save_iter_sidecar_safe",
        return_value=False,  # simulate persistent write failure
    ):
        # Should not raise — failure is logged, not propagated.
        w.on_started(input_prompt="", system_prompt="", last_seq=100)
        w.on_text_delta("hello", 101)
        w.flush()

    # No .tmp residue in runs_dir.
    assert list(tmp_path.glob("*.tmp")) == []


def test_writer_uses_safe_save_wrapper(tmp_path: Path):
    """Writer must delegate to save_iter_sidecar_safe (R3 contract), not
    bypass it with raw atomic_write_json or open()."""
    w = _make_writer(tmp_path)
    with patch(
        "harness.persistence.sidecar_writer.save_iter_sidecar_safe",
        return_value=True,
    ) as mock_save:
        w.on_started(input_prompt="", system_prompt="", last_seq=100)
    assert mock_save.called
    # Verify the args are correct (run_id, node_id, iter_num, data, runs_dir).
    call_args = mock_save.call_args
    assert call_args.args[0] == "r1"
    assert call_args.args[1] == "scout"
    assert call_args.args[2] == 1
    assert isinstance(call_args.args[3], dict)


# ── P2b-T20: finalize clears streaming_text ──────────────────────────


def test_finalize_clears_streaming_text(tmp_path: Path):
    """After finalize, sidecar.streaming_text must be '' even if we streamed
    a lot of text. output_result must be set to the provided value."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    w.on_text_delta("lots of streaming text", 101)
    w.flush()  # force the streaming content to disk

    pre_finalize = json.loads(w.path.read_text())
    assert pre_finalize["streaming_text"] == "lots of streaming text"

    w.finalize(output_result={"done": True}, last_seq=200)

    post = json.loads(w.path.read_text())
    assert post["status"] == "completed"
    assert post["streaming_text"] == ""
    assert post["output_result"] == {"done": True}
    assert post["last_seq"] == 200


# ── P2b-T21: mark_failed ─────────────────────────────────────────────


def test_mark_failed_status(tmp_path: Path):
    """mark_failed sets status=failed, records error, preserves streaming_text."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    w.on_text_delta("partial output before crash", 101)
    w.flush()

    w.mark_failed(error="OOM", last_seq=110)

    data = json.loads(w.path.read_text())
    assert data["status"] == "failed"
    assert data["error"] == "OOM"
    # Critical: streaming_text + tool_calls preserved for debugging.
    assert data["streaming_text"] == "partial output before crash"
    assert data["last_seq"] == 110
    assert data["ended_at"] is not None


def test_mark_interrupted_status(tmp_path: Path):
    """mark_interrupted sets status=interrupted (startup-sweep path)."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    w.on_text_delta("streaming when process died", 101)
    w.flush()

    w.mark_interrupted(last_seq=105)

    data = json.loads(w.path.read_text())
    assert data["status"] == "interrupted"
    # Preserve streaming text + tool_calls as evidence.
    assert data["streaming_text"] == "streaming when process died"


# ── Schema conformance ───────────────────────────────────────────────


def test_sidecar_writer_output_validates_against_v2_schema(tmp_path: Path):
    """The sidecar dict the writer produces must validate against the v2 schema."""
    from harness.persistence.validate import validate_iter_sidecar

    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    data = json.loads(w.path.read_text())
    errors = validate_iter_sidecar(data)
    assert errors == [], f"schema violations: {errors}"


# ── Registry + event routing ─────────────────────────────────────────


def test_registry_creates_writer_on_node_started(tmp_path: Path):
    """Bus node.started event creates a writer and triggers on_started."""
    reg = InflightWriterRegistry(runs_dir=tmp_path)
    event = {
        "type": "node.started",
        "seq": 100,
        "payload": {
            "run_id": "r1",
            "node_id": "scout",
            "iteration": 1,
            "input_prompt": "hi",
            "system_prompt": "sys",
        },
    }
    reg.route_event(event)
    assert reg.active_count() == 1
    writer = reg.get("r1", "scout", 1)
    assert writer is not None
    assert writer.status == "streaming"
    assert (tmp_path / "r1+iters+scout+1.json").exists()


def test_registry_cleans_up_on_node_completed(tmp_path: Path):
    """Bus node.completed finalizes the writer AND removes it from registry."""
    reg = InflightWriterRegistry(runs_dir=tmp_path)
    reg.route_event({
        "type": "node.started", "seq": 100,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "input_prompt": "", "system_prompt": ""},
    })
    assert reg.active_count() == 1
    reg.route_event({
        "type": "node.completed", "seq": 200,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "output_result": {"summary": "done"}},
    })
    assert reg.active_count() == 0
    # Sidecar on disk is finalized.
    data = json.loads((tmp_path / "r1+iters+scout+1.json").read_text())
    assert data["status"] == "completed"


def test_registry_routes_text_delta_to_active_writer(tmp_path: Path):
    """agent.text_delta routes to the already-created writer."""
    reg = InflightWriterRegistry(runs_dir=tmp_path, debounce_ms=0)
    reg.route_event({
        "type": "node.started", "seq": 100,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "input_prompt": "", "system_prompt": ""},
    })
    reg.route_event({
        "type": "agent.text_delta", "seq": 101,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "text": "hello"},
    })
    # debounce_ms=0 means the delta flushes immediately.
    writer = reg.get("r1", "scout", 1)
    assert writer.streaming_text == "hello"
    assert writer.last_seq == 101


def test_registry_ignores_unknown_event_types(tmp_path: Path):
    """Unknown event types are silently dropped (forward-compat)."""
    reg = InflightWriterRegistry(runs_dir=tmp_path)
    reg.route_event({"type": "some.future.event", "seq": 1, "payload": {}})
    assert reg.active_count() == 0


def test_attach_to_bus_returns_detach_callable(tmp_path: Path):
    """attach_to_bus registers + returns a detach function."""
    from harness.extensions.bus import Bus

    bus = Bus()
    reg = InflightWriterRegistry(runs_dir=tmp_path)
    detach = attach_to_bus(bus, reg)
    assert callable(detach)
    assert reg.route_event in bus._sync_listeners

    detach()


# ── tool_call_id matching (parallel same-name calls) ─────────────────


def test_on_tool_result_matches_by_tool_call_id_not_name(tmp_path: Path):
    """Parallel same-name tool calls must pair by tool_call_id, not by name.

    Reproduces the original bug: pydantic-ai yields both function_tool_call
    events upfront, then results one at a time. Name-based reverse matching
    lands result A on call B. With ID-based matching, each result lands on
    its own call.
    """
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    # Two parallel bash calls — same name, different IDs.
    w.on_tool_call({"tool_name": "bash", "tool_args": {"cmd": "ls"}, "tool_call_id": "A"}, 101)
    w.on_tool_call({"tool_name": "bash", "tool_args": {"cmd": "pwd"}, "tool_call_id": "B"}, 102)
    # Result for A arrives first.
    w.on_tool_result("bash", "result-for-A", 103, tool_call_id="A")

    w.flush()
    data = json.loads(w.path.read_text())
    assert data["tool_calls"][0]["tool_call_id"] == "A"
    assert data["tool_calls"][0]["tool_result"] == "result-for-A"
    # B must NOT receive A's result (the bug).
    assert data["tool_calls"][1]["tool_call_id"] == "B"
    assert "tool_result" not in data["tool_calls"][1]

    # Now result for B arrives — lands on B, leaves A untouched.
    w.on_tool_result("bash", "result-for-B", 104, tool_call_id="B")
    w.flush()
    data = json.loads(w.path.read_text())
    assert data["tool_calls"][0]["tool_result"] == "result-for-A"
    assert data["tool_calls"][1]["tool_result"] == "result-for-B"


def test_on_tool_result_unknown_tool_call_id_drops_with_warning(tmp_path: Path):
    """Unknown tool_call_id must not pollute any existing entry; warn + drop."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    w.on_tool_call({"tool_name": "bash", "tool_args": {}, "tool_call_id": "A"}, 101)

    # Result arrives claiming an ID we never saw.
    with patch.object(
        __import__("harness.persistence.sidecar_writer", fromlist=["logger"]).logger,
        "warning",
    ) as mock_warn:
        w.on_tool_result("bash", "orphan", 102, tool_call_id="Z")
        assert mock_warn.called, "expected drop warning for unknown tool_call_id"

    w.flush()
    data = json.loads(w.path.read_text())
    assert "tool_result" not in data["tool_calls"][0], "orphan result must not attach"


def test_on_tool_result_without_tool_call_id_drops_with_warning(tmp_path: Path):
    """Missing tool_call_id (legacy pydantic-ai or synthetic event) drops, no crash."""
    w = _make_writer(tmp_path)
    w.on_started(input_prompt="", system_prompt="", last_seq=100)
    w.on_tool_call({"tool_name": "bash", "tool_args": {}, "tool_call_id": "A"}, 101)

    w.on_tool_result("bash", "no-id", 102)  # no tool_call_id kwarg

    w.flush()
    data = json.loads(w.path.read_text())
    assert "tool_result" not in data["tool_calls"][0]


def test_registry_routes_tool_call_id_end_to_end(tmp_path: Path):
    """Bus agent.tool_call / agent.tool_result events carry tool_call_id
    through the registry into the persisted sidecar entry."""
    reg = InflightWriterRegistry(runs_dir=tmp_path, debounce_ms=0)
    reg.route_event({
        "type": "node.started", "seq": 100,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "input_prompt": "", "system_prompt": ""},
    })
    reg.route_event({
        "type": "agent.tool_call", "seq": 101,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "tool_name": "bash", "tool_args": {"cmd": "ls"},
                    "tool_call_id": "call_xyz"},
    })
    reg.route_event({
        "type": "agent.tool_result", "seq": 102,
        "payload": {"run_id": "r1", "node_id": "scout", "iteration": 1,
                    "tool_name": "bash", "result": "ok",
                    "tool_call_id": "call_xyz"},
    })

    writer = reg.get("r1", "scout", 1)
    writer.flush()
    data = json.loads(writer.path.read_text())
    assert data["tool_calls"][0]["tool_call_id"] == "call_xyz"
    assert data["tool_calls"][0]["tool_result"] == "ok"
