"""Test node execution phases — pure functions extracted from macro_graph."""
import pytest
from harness.engine.node_phases import (
    check_upstream_errors,
    NodeSkipResult,
    build_node_started_payload,
    build_node_completed_payload,
    build_node_failed_payload,
    build_extension_context,
)


# ---------------------------------------------------------------------------
# check_upstream_errors
# ---------------------------------------------------------------------------

def test_check_upstream_errors_all_clean():
    state = {"errors": {}, "outputs": {}}
    result = check_upstream_errors(state, ["dep1", "dep2"])
    assert result is None


def test_check_upstream_errors_found():
    state = {"errors": {"dep1": {"error": "timeout"}}, "outputs": {}}
    result = check_upstream_errors(state, ["dep1", "dep2"])
    assert result is not None
    assert isinstance(result, NodeSkipResult)
    assert result.failed_dep == "dep1"
    assert result.error_info == {"error": "timeout"}


def test_check_upstream_errors_no_deps():
    state = {"errors": {"other": {"error": "fail"}}, "outputs": {}}
    result = check_upstream_errors(state, [])
    assert result is None


def test_check_upstream_errors_empty_deps_with_errors():
    """Empty deps list should always return None (no deps to check)."""
    state = {"errors": {"x": {"error": "fail"}}}
    assert check_upstream_errors(state, []) is None


def test_check_upstream_errors_first_dep_fails():
    """Should return the first failed dependency found."""
    state = {"errors": {"dep2": "crash"}}
    result = check_upstream_errors(state, ["dep1", "dep2", "dep3"])
    assert result is not None
    assert result.failed_dep == "dep2"


def test_check_upstream_errors_missing_errors_key():
    """State with no 'errors' key at all should return None."""
    state = {}
    assert check_upstream_errors(state, ["dep1"]) is None


def test_check_upstream_errors_dep_not_in_errors():
    """Deps that are not in the errors dict should be skipped."""
    state = {"errors": {"other": "boom"}}
    result = check_upstream_errors(state, ["dep1"])
    assert result is None


def test_check_upstream_errors_string_error_value():
    """Error values may be strings, not dicts — should still work."""
    state = {"errors": {"dep1": "simple error string"}}
    result = check_upstream_errors(state, ["dep1"])
    assert result is not None
    assert result.failed_dep == "dep1"
    assert result.error_info == "simple error string"


# ---------------------------------------------------------------------------
# build_node_started_payload
# ---------------------------------------------------------------------------

def test_build_node_started_payload():
    p = build_node_started_payload("wf1", "n1", "agent1", model="gpt-4")
    assert p["workflow_id"] == "wf1"
    assert p["node_id"] == "n1"
    assert p["agent_name"] == "agent1"
    assert p["model"] == "gpt-4"
    assert "ts" in p


def test_build_node_started_payload_with_tools():
    p = build_node_started_payload("wf1", "n1", "agent1", model="gpt-4", tools=["bash"])
    assert p["tools"] == ["bash"]


def test_build_node_started_payload_defaults():
    p = build_node_started_payload("wf1", "n1", "agent1")
    assert p["attempt"] == 1
    assert "ts" in p


# ---------------------------------------------------------------------------
# build_node_completed_payload
# ---------------------------------------------------------------------------

def test_build_node_completed_payload():
    p = build_node_completed_payload("wf1", "n1", "agent1", "output text", 1500.5, {"input": 100, "output": 50})
    assert p["workflow_id"] == "wf1"
    assert p["node_id"] == "n1"
    assert p["agent_name"] == "agent1"
    assert p["duration_ms"] == 1500.5
    assert p["token_usage"]["input"] == 100
    assert p["status"] == "success"


def test_build_node_completed_payload_no_token_usage():
    p = build_node_completed_payload("wf1", "n1", "agent1", "output", 100.0)
    assert p["workflow_id"] == "wf1"
    assert p["duration_ms"] == 100.0
    assert "token_usage" not in p


def test_build_node_completed_payload_with_io_data():
    io_data = {"input_prompt": "ctx", "system_prompt": "sys", "output_result": "out"}
    p = build_node_completed_payload("wf1", "n1", "agent1", "output", 100.0, io_data=io_data)
    assert p["input_prompt"] == "ctx"
    assert p["output_result"] == "out"


# ---------------------------------------------------------------------------
# build_node_failed_payload
# ---------------------------------------------------------------------------

def test_build_node_failed_payload():
    p = build_node_failed_payload("wf1", "n1", "agent1", "crashed", 500.0)
    assert p["workflow_id"] == "wf1"
    assert p["node_id"] == "n1"
    assert p["agent_name"] == "agent1"
    assert p["error"] == "crashed"
    assert p["duration_ms"] == 500.0


def test_build_node_failed_payload_defaults():
    p = build_node_failed_payload("wf1", "n1", "agent1", "err", 100)
    assert p["attempt"] == 1
    assert p["will_retry"] is False


def test_build_node_failed_payload_custom_error_type():
    p = build_node_failed_payload("wf1", "n1", "agent1", "err", 100, error_type="TimeoutError")
    assert p["error_type"] == "TimeoutError"


def test_build_node_failed_payload_with_extra():
    p = build_node_failed_payload("wf1", "n1", "agent1", "err", 100, extra={"tool_calls_before_failure": []})
    assert p["tool_calls_before_failure"] == []


# ---------------------------------------------------------------------------
# build_extension_context
# ---------------------------------------------------------------------------

def test_build_extension_context_basic():
    """build_extension_context should return a NodeCtx with correct fields."""
    ctx = build_extension_context(
        workflow_id="wf1",
        workflow_name="test_workflow",
        node_id="n1",
        agent_name="agent1",
        prompt="do something",
        system_prompt="you are helpful",
        upstream_outputs={"dep1": "result1"},
        config_model="gpt-4",
        config_retries=2,
        config_tools=["bash"],
        config_tool_info={"bash": {}},
        config_agent_md_path="/path/to/agent.md",
        config_critique=None,
        config_result_type_name=None,
    )
    assert ctx.workflow.workflow_id == "wf1"
    assert ctx.workflow.workflow_name == "test_workflow"
    assert ctx.node_id == "n1"
    assert ctx.agent_name == "agent1"
    assert ctx.prompt == "do something"
    assert len(ctx.messages) == 2
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"] == "you are helpful"
    assert ctx.messages[1]["role"] == "user"
    assert ctx.messages[1]["content"] == "do something"
    assert ctx.upstream_outputs == {"dep1": "result1"}


def test_build_extension_context_inputs():
    ctx = build_extension_context(
        workflow_id="wf1",
        workflow_name="wf",
        node_id="n1",
        agent_name="agent1",
        prompt="p",
        system_prompt="s",
        upstream_outputs={},
        inputs={"key": "value"},
    )
    assert ctx.workflow.inputs == {"key": "value"}
