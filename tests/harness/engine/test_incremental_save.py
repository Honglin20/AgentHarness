"""Test _build_iter_data — pure function extracted from _save_incremental.

Covers the dispatch_info (backend + tools_resolved) persistence contract:
v3.1 badge fields for frontend backend badge rendering during replay.
"""
from dataclasses import dataclass

from harness.engine.incremental_save import _build_iter_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_kwargs(**overrides) -> dict:
    """Minimal kwargs for _build_iter_data. Callers override specific fields."""
    base = {
        "agent_io_snapshot": {},
        "todo_states": {},
        "node_id": "trainer",
        "iter_num": 1,
        "duration_ms": 5000,
        "status": "completed",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Dispatch info — badge persistence (v3.1)
# ---------------------------------------------------------------------------


class TestBuildIterDataDispatchInfo:
    """backend + tools_resolved (the 'backend badge') persisted into sidecar.

    The frontend reads these fields during REPLAY to render the backend badge
    + per-tool mapping. Without this persistence, the badge only shows during
    live WS (ephemeral node.started payload).
    """

    def test_dispatch_info_none_omits_badge_fields(self):
        """Backward compat: dispatch_info=None → no backend/tools_resolved in output.
        Old in-flight runs and legacy callers don't pass dispatch_info — the
        sidecar must not contain these fields (frontend degrades gracefully)."""
        data = _build_iter_data(**_minimal_kwargs(dispatch_info=None))
        assert "backend" not in data
        assert "tools_resolved" not in data

    def test_dispatch_info_empty_dict_emits_null_fields(self):
        """Empty dict dispatch_info → backend=None, tools_resolved=None.
        Defensive: treat an empty dict as 'explicitly set to nothing' rather
        than crashing. The frontend renders null/None as 'no badge'."""
        data = _build_iter_data(**_minimal_kwargs(dispatch_info={}))
        assert data["backend"] is None
        assert data["tools_resolved"] is None

    def test_dispatch_info_with_backend_only(self):
        """dispatch_info with only backend → backend set, tools_resolved=None."""
        data = _build_iter_data(
            **_minimal_kwargs(dispatch_info={"backend": "claude-code"})
        )
        assert data["backend"] == "claude-code"
        assert data["tools_resolved"] is None

    def test_dispatch_info_with_tools_resolved(self):
        """Full dispatch_info → both fields persisted."""
        tools = [
            {"declared": "bash", "resolved": "Bash", "source": "Claude built-in"},
            {"declared": "ask_user", "resolved": "mcp__harness__ask_user",
             "source": "harness MCP"},
        ]
        data = _build_iter_data(
            **_minimal_kwargs(dispatch_info={
                "backend": "claude-code",
                "tools_resolved": tools,
            })
        )
        assert data["backend"] == "claude-code"
        assert data["tools_resolved"] == tools

    def test_dispatch_info_with_v3_streaming_state(self):
        """Badge fields coexist with v3 streaming_state fields — both are
        independently controlled. No regression on the existing v3 path."""
        streaming = {
            "streaming_text": "processing...",
            "thinking": "",
            "tool_streaming_outputs": {},
            "last_seq": 42,
        }
        tools = [{"declared": "bash", "resolved": "Bash", "source": "Claude built-in"}]
        data = _build_iter_data(
            **_minimal_kwargs(
                streaming_state=streaming,
                dispatch_info={
                    "backend": "pydantic-ai",
                    "tools_resolved": tools,
                },
            )
        )
        # v3 fields present
        assert data["schema_version"] == 3
        assert data["streaming_text"] == "processing..."
        assert data["last_seq"] == 42
        # badge fields present alongside v3 fields
        assert data["backend"] == "pydantic-ai"
        assert data["tools_resolved"] == tools

    def test_dispatch_info_v2_sidecar_no_streaming_state(self):
        """dispatch_info without streaming_state → badge fields on v2 sidecar.
        v2 sidecars also need badge data (not just v3)."""
        data = _build_iter_data(
            **_minimal_kwargs(
                streaming_state=None,
                dispatch_info={"backend": "claude-code", "tools_resolved": []},
            )
        )
        assert "schema_version" not in data  # v2
        assert data["backend"] == "claude-code"
        assert data["tools_resolved"] == []


# ---------------------------------------------------------------------------
# Basic structure — smoke test (unchanged contract)
# ---------------------------------------------------------------------------


class TestBuildIterDataBasic:
    """Sanity-check the remaining fields so dispatch_info tests have a stable
    baseline. These mirror the Phase 3 tests already in test_phase3_e2e_api.py
    but exercise _build_iter_data directly (not via fixture files)."""

    def test_minimal_sidecar_shape(self):
        data = _build_iter_data(**_minimal_kwargs())
        assert data["iter"] == 1
        assert data["node_id"] == "trainer"
        assert data["status"] == "completed"
        assert data["duration_ms"] == 5000
        assert data["tool_calls"] == []
        assert data["todo_steps"] == []

    def test_summary_extracted_from_output_result(self):
        kwargs = _minimal_kwargs(
            agent_io_snapshot={
                "trainer": {"output_result": {"summary": "training complete"}},
            },
        )
        data = _build_iter_data(**kwargs)
        assert data["summary"] == "training complete"

    def test_tool_calls_carried_from_agent_io(self):
        tool_calls = [
            {"tool_name": "Bash", "tool_args": {"command": "ls"}, "tool_result": "ok"},
        ]
        kwargs = _minimal_kwargs(
            agent_io_snapshot={"trainer": {"tool_calls": tool_calls}},
        )
        data = _build_iter_data(**kwargs)
        assert data["tool_calls"] == tool_calls

    def test_todo_steps_filtered_by_iteration(self):
        todo_states = {
            "trainer": [
                {"task_id": "t1", "content": "step1", "iteration": 1},
                {"task_id": "t2", "content": "step2", "iteration": 1},
                {"task_id": "t3", "content": "other iter", "iteration": 2},
            ],
        }
        data = _build_iter_data(**_minimal_kwargs(todo_states=todo_states))
        assert len(data["todo_steps"]) == 2
        assert {s["task_id"] for s in data["todo_steps"]} == {"t1", "t2"}
