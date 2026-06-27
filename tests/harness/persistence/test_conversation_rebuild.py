"""Tests for harness/persistence/conversation_rebuild.py.

The rebuild function bridges main record → sidecar source-of-truth. These
tests cover the empty / complete / multi-iter / corrupt / v3-fields matrix.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.persistence import run_store as run_store_module
from harness.persistence.conversation_rebuild import rebuild_conversation_from_sidecars
from harness.persistence.run_store import RunStore


# ──────────────────────────────────────────────────────────────────────────
# Helpers — write sidecars + iter_index directly to a tmp runs_dir
# ──────────────────────────────────────────────────────────────────────────

def _write_sidecar(
    runs_dir: Path,
    run_id: str,
    node_id: str,
    iter_num: int,
    *,
    output: Any = None,
    tool_calls: list[dict] | None = None,
    thinking: str = "",
    tool_streaming_outputs: dict | None = None,
    input_prompt: str | None = None,
) -> None:
    """Write one iter sidecar file matching InflightSidecarWriter's format."""
    payload: dict[str, Any] = {
        "iter": iter_num,
        "node_id": node_id,
        "status": "completed",
        "duration_ms": 1000,
        "input_prompt": input_prompt,
        "system_prompt": None,
        "output_result": output,
        "tool_calls": tool_calls or [],
        "thinking": thinking,
        "tool_streaming_outputs": tool_streaming_outputs or {},
        "last_seq": 0,
    }
    path = runs_dir / f"{run_id}+iters+{node_id}+{iter_num}.json"
    path.write_text(json.dumps(payload))


def _write_iter_index(runs_dir: Path, run_id: str, index: dict[str, list[dict]]) -> None:
    """Write the iter_index sidecar."""
    path = runs_dir / f"{run_id}+iter_index.json"
    path.write_text(json.dumps(index))


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch):
    """Construct a RunStore against tmp_path and patch the module-level
    singleton so rebuild_conversation_from_sidecars uses it."""
    store = RunStore(runs_dir=tmp_path)
    monkeypatch.setattr(run_store_module, "_run_store_singleton", store)
    return store


def _make_tool_call(name: str, call_id: str, result: str = "ok") -> dict:
    return {
        "tool_name": name,
        "tool_args": {"x": 1},
        "tool_result": result,
        "tool_call_id": call_id,
    }


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

def test_returns_empty_when_no_sidecars(isolated_store, tmp_path):
    """Legacy / setup-only runs have no iter_index → caller falls back."""
    result = rebuild_conversation_from_sidecars("run1", {})
    assert result == []


def test_returns_empty_when_iter_index_present_but_no_sidecar_files(isolated_store, tmp_path):
    """iter_index exists but sidecar files are missing → empty."""
    _write_iter_index(tmp_path, "run1", {"agent_a": [{"iter": 1, "status": "completed"}]})
    result = rebuild_conversation_from_sidecars("run1", {})
    assert result == []


def test_rebuild_replaces_truncated_conversation(isolated_store, tmp_path):
    """3 agents × 1 iter × (1 output + 2 tool_calls) → 9 messages."""
    _write_iter_index(tmp_path, "run1", {
        "setup": [{"iter": 1, "status": "completed"}],
        "baseline": [{"iter": 1, "status": "completed"}],
        "analyzer": [{"iter": 1, "status": "completed"}],
    })
    for node in ("setup", "baseline", "analyzer"):
        _write_sidecar(
            tmp_path, "run1", node, 1,
            output={"summary": f"{node} done"},
            tool_calls=[
                _make_tool_call("bash", f"{node}_call_1"),
                _make_tool_call("Read", f"{node}_call_2"),
            ],
        )

    messages = rebuild_conversation_from_sidecars("run1", {})
    assert len(messages) == 9  # 3 × (1 output + 2 tool_calls)
    # Per-node breakdown
    by_node: dict[str, list[dict]] = {}
    for m in messages:
        by_node.setdefault(m["nodeId"], []).append(m)
    for node in ("setup", "baseline", "analyzer"):
        assert len(by_node[node]) == 3
        types = sorted(m["type"] for m in by_node[node])
        assert types == ["agent", "tool_call", "tool_call"]


def test_rebuild_preserves_multi_iter_history(isolated_store, tmp_path):
    """Same node, 2 iters → 2 message groups, each stamped with its iter."""
    _write_iter_index(tmp_path, "run1", {
        "trainer": [
            {"iter": 1, "status": "completed"},
            {"iter": 2, "status": "completed"},
        ],
    })
    _write_sidecar(tmp_path, "run1", "trainer", 1,
                   output={"summary": "iter 1 result"},
                   tool_calls=[_make_tool_call("bash", "c1")])
    _write_sidecar(tmp_path, "run1", "trainer", 2,
                   output={"summary": "iter 2 result"},
                   tool_calls=[_make_tool_call("bash", "c2")])

    messages = rebuild_conversation_from_sidecars("run1", {})
    # 2 iters × (1 output + 1 tool_call) = 4 messages
    assert len(messages) == 4
    iters_seen = sorted(m["iteration"] for m in messages)
    assert iters_seen == [1, 1, 2, 2]


def test_rebuild_skips_corrupt_sidecar_gracefully(isolated_store, tmp_path):
    """A corrupt sidecar file is skipped; remaining sidecars still surface."""
    _write_iter_index(tmp_path, "run1", {
        "good": [{"iter": 1, "status": "completed"}],
        "bad": [{"iter": 1, "status": "completed"}],
    })
    _write_sidecar(tmp_path, "run1", "good", 1,
                   output={"summary": "ok"},
                   tool_calls=[_make_tool_call("bash", "g1")])
    # Write garbage to bad sidecar
    (tmp_path / "run1+iters+bad+1.json").write_text("not valid json {{{")

    messages = rebuild_conversation_from_sidecars("run1", {})
    # Only good agent's 2 messages should come through
    assert len(messages) == 2
    assert all(m["nodeId"] == "good" for m in messages)


def test_rebuild_preserves_thinking_and_tool_streaming(isolated_store, tmp_path):
    """Sidecar v3 fields (thinking + tool_streaming_outputs) propagate to messages."""
    _write_iter_index(tmp_path, "run1", {
        "agent": [{"iter": 1, "status": "completed"}],
    })
    _write_sidecar(
        tmp_path, "run1", "agent", 1,
        output={"summary": "done"},
        thinking="Let me reason about this.",
        tool_calls=[_make_tool_call("bash", "call_x", result="line1\nline2\n")],
        tool_streaming_outputs={"call_x": "line1\nline2\n"},
    )

    messages = rebuild_conversation_from_sidecars("run1", {})
    assert len(messages) == 2
    agent_msg = next(m for m in messages if m["type"] == "agent")
    assert agent_msg["thinking"] == "Let me reason about this."

    tool_msg = next(m for m in messages if m["type"] == "tool_call")
    assert tool_msg["toolStreamingOutput"] == "line1\nline2\n"


def test_rebuild_never_raises_on_unexpected_error(isolated_store, tmp_path, monkeypatch):
    """Rebuild must not raise — empty list signals 'use fallback'."""
    # Force get_iter_index to blow up
    def _boom(_run_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(isolated_store, "get_iter_index", _boom)
    result = rebuild_conversation_from_sidecars("run1", {})
    assert result == []


def test_rebuild_works_with_empty_agent_io(isolated_store, tmp_path):
    """Caller may pass {} — build_conversation handles it."""
    _write_iter_index(tmp_path, "run1", {"agent": [{"iter": 1, "status": "completed"}]})
    _write_sidecar(tmp_path, "run1", "agent", 1,
                   output={"summary": "ok"},
                   tool_calls=[_make_tool_call("bash", "c1")])

    messages = rebuild_conversation_from_sidecars("run1", {})
    assert len(messages) == 2
