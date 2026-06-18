"""Unit tests for P2a: per-iter sidecar content (tool_calls + todo_steps).

Covers:
  - _build_iter_data (harness.engine.incremental_save) — sidecar payload construction
  - _iter_sidecar_to_messages (server.routers.runs) — API projection

ADR basis:
  - D2: sidecar must carry tool_calls
  - O1: todo_steps filtered by iter (not full list per sidecar)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure server package is importable when running from project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from harness.engine.incremental_save import _build_iter_data


# ── P2a-T05: tool_calls write + projection ───────────────────────────


def test_build_iter_data_includes_tool_calls_from_agent_io():
    """D2: sidecar must carry tool_calls copied from agent_io[node]."""
    agent_io = {
        "scout": {
            "input_prompt": "do thing",
            "output_result": {"summary": "done"},
            "tool_calls": [
                {"tool_name": "bash", "tool_args": {"command": "ls"}, "tool_result": "file1\nfile2"},
                {"tool_name": "TodoTool", "tool_args": {"op": "create"}, "tool_result": "ok"},
            ],
        }
    }
    data = _build_iter_data(
        agent_io_snapshot=agent_io,
        todo_states={},
        node_id="scout",
        iter_num=1,
        duration_ms=500,
        status="completed",
    )
    assert data["tool_calls"] == agent_io["scout"]["tool_calls"]
    assert len(data["tool_calls"]) == 2


def test_build_iter_data_tool_calls_empty_when_agent_io_missing():
    """Node not in agent_io → tool_calls is [] (defensive, not None)."""
    data = _build_iter_data(
        agent_io_snapshot={},
        todo_states={},
        node_id="absent",
        iter_num=1,
        duration_ms=None,
        status="completed",
    )
    assert data["tool_calls"] == []
    assert data["todo_steps"] == []


def test_build_iter_data_tool_calls_empty_when_field_not_list():
    """If agent_io[node].tool_calls is corrupt (not a list), fall back to []."""
    agent_io = {"scout": {"tool_calls": "not-a-list"}}
    data = _build_iter_data(
        agent_io_snapshot=agent_io,
        todo_states={},
        node_id="scout",
        iter_num=1,
        duration_ms=None,
        status="completed",
    )
    assert data["tool_calls"] == []


def test_iter_sidecar_to_messages_projects_tool_calls():
    """API: sidecar.tool_calls → tool_call messages for the frontend."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {
        "iter": 1,
        "node_id": "scout",
        "output": {"summary": "done"},
        "tool_calls": [
            {"tool_name": "bash", "tool_args": {"command": "ls"}, "tool_result": "out"},
            {"tool_name": "TodoTool", "tool_args": {"op": "create"}, "tool_result": "ok"},
        ],
    }
    messages = _iter_sidecar_to_messages(sidecar, "scout", 1)
    tool_messages = [m for m in messages if m["type"] == "tool_call"]
    assert len(tool_messages) == 2
    assert all(m["nodeId"] == "scout" and m["iteration"] == 1 for m in tool_messages)
    assert tool_messages[0]["toolName"] == "bash"
    assert tool_messages[0]["toolArgs"] == {"command": "ls"}
    assert tool_messages[0]["toolResult"] == "out"
    assert tool_messages[0]["toolStatus"] == "done"


def test_iter_sidecar_to_messages_handles_null_tool_result():
    """tool_result=None must not crash projection."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {
        "iter": 1,
        "node_id": "scout",
        "tool_calls": [
            {"tool_name": "wait", "tool_args": {}, "tool_result": None},
        ],
    }
    messages = _iter_sidecar_to_messages(sidecar, "scout", 1)
    tool_messages = [m for m in messages if m["type"] == "tool_call"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["toolResult"] is None


def test_iter_sidecar_to_messages_no_tool_calls_field():
    """Legacy sidecar without tool_calls → no tool_call messages, no crash."""
    from server.routers.runs import _iter_sidecar_to_messages

    sidecar = {"iter": 1, "node_id": "scout", "output": {"summary": "ok"}}
    messages = _iter_sidecar_to_messages(sidecar, "scout", 1)
    assert all(m["type"] != "tool_call" for m in messages)


# ── P2a-T06: todo_steps per-iter filter ──────────────────────────────


def test_build_iter_data_filters_todo_steps_by_iter():
    """O1: todo_steps in sidecar contains only the matching iter's steps.

    Setup: 5 steps total — 3 for iter=1, 2 for iter=2. Building iter=1's
    sidecar must include only the 3 iter=1 steps.
    """
    todo_states = {
        "scout": [
            {"task_id": "t1", "content": "a", "status": "completed", "iteration": 1},
            {"task_id": "t2", "content": "b", "status": "completed", "iteration": 1},
            {"task_id": "t3", "content": "c", "status": "in_progress", "iteration": 1},
            {"task_id": "t4", "content": "d", "status": "pending", "iteration": 2},
            {"task_id": "t5", "content": "e", "status": "pending", "iteration": 2},
        ]
    }
    data_iter1 = _build_iter_data(
        agent_io_snapshot={},
        todo_states=todo_states,
        node_id="scout",
        iter_num=1,
        duration_ms=None,
        status="completed",
    )
    assert len(data_iter1["todo_steps"]) == 3
    assert all(s["iteration"] == 1 for s in data_iter1["todo_steps"])
    assert {s["task_id"] for s in data_iter1["todo_steps"]} == {"t1", "t2", "t3"}

    data_iter2 = _build_iter_data(
        agent_io_snapshot={},
        todo_states=todo_states,
        node_id="scout",
        iter_num=2,
        duration_ms=None,
        status="completed",
    )
    assert len(data_iter2["todo_steps"]) == 2
    assert {s["task_id"] for s in data_iter2["todo_steps"]} == {"t4", "t5"}


def test_build_iter_data_todo_steps_empty_when_no_match():
    """Building iter=3 sidecar when no steps have iteration=3 → empty list."""
    todo_states = {"scout": [{"task_id": "t1", "content": "x", "iteration": 1}]}
    data = _build_iter_data(
        agent_io_snapshot={},
        todo_states=todo_states,
        node_id="scout",
        iter_num=99,
        duration_ms=None,
        status="completed",
    )
    assert data["todo_steps"] == []


def test_build_iter_data_excludes_steps_missing_iteration():
    """Defensive: a malformed step without ``iteration`` is skipped, not crashed."""
    todo_states = {
        "scout": [
            {"task_id": "good", "content": "ok", "iteration": 1},
            {"task_id": "bad", "content": "no iteration field"},  # missing
            {"task_id": "wrong_type", "content": "str iter", "iteration": "1"},  # not int
        ]
    }
    data = _build_iter_data(
        agent_io_snapshot={},
        todo_states=todo_states,
        node_id="scout",
        iter_num=1,
        duration_ms=None,
        status="completed",
    )
    assert len(data["todo_steps"]) == 1
    assert data["todo_steps"][0]["task_id"] == "good"


def test_build_iter_data_empty_todo_states():
    """No todo_states at all → empty list, no crash."""
    data = _build_iter_data(
        agent_io_snapshot={},
        todo_states={},
        node_id="scout",
        iter_num=1,
        duration_ms=None,
        status="completed",
    )
    assert data["todo_steps"] == []
