from pathlib import Path
from unittest.mock import MagicMock

from harness.api import Agent, AgentResult
from harness.engine.macro_graph import (
    MacroGraphBuilder,
    request_stop_and_regenerate,
)
from harness.engine.schema_utils import validate_output as _validate_output


def _make_workflow(agents, workflow_dir=None):
    wf = MagicMock()
    wf.agents = agents
    wf.workflow_dir = workflow_dir or Path(__file__).resolve().parent.parent / "compiler" / "fixtures"
    return wf


def test_build_linear_graph():
    """Linear A -> B produces correct nodes and edges."""
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)
    compiled = graph.compile()
    assert compiled is not None


def test_build_single_node_graph():
    """Single node with no dependencies."""
    agents = [Agent("analyzer", after=[])]
    workflow = _make_workflow(agents)

    builder = MacroGraphBuilder()
    graph = builder.build(workflow)
    compiled = graph.compile()
    assert compiled is not None


# --- _validate_output tests ---

def test_validate_output_accepts_valid_basemodel():
    """Valid BaseModel output should pass validation."""
    valid = AgentResult(summary="Task completed")
    assert _validate_output(valid, AgentResult) is None


def test_validate_output_rejects_none():
    """None output should fail validation."""
    result = _validate_output(None, AgentResult)
    assert result is not None
    assert "no output" in result.lower()


def test_validate_output_rejects_wrong_type():
    """Non-BaseModel output when BaseModel expected should fail."""
    result = _validate_output("just a string", AgentResult)
    assert result is not None
    assert "expected" in result.lower() or "AgentResult" in result


def test_validate_output_none_result_type_passes_anything():
    """When result_type is None, any output should pass."""
    assert _validate_output("anything", None) is None
    assert _validate_output(None, None) is None


# --- Interrupt signal TTL tests ---

def test_stop_regen_signal_ttl_expiry():
    """Interrupt signal older than 60 seconds should be expired and cleaned up."""
    import asyncio
    import time

    builder = MacroGraphBuilder()
    builder.workflow_id = "test_wf_ttl"
    builder._pending_stop_regen.clear()

    asyncio.get_event_loop().run_until_complete(
        builder.request_stop_and_regenerate("agent_a", "partial", "guidance")
    )

    # Fresh signal should be detected
    assert builder._has_pending_stop_regen("test_wf_ttl", "agent_a") is True

    # Manually backdate the timestamp to simulate expiry
    builder._pending_stop_regen["test_wf_ttl"]["_ts"] = time.time() - 61

    # Should be expired
    assert builder._has_pending_stop_regen("test_wf_ttl", "agent_a") is False
    # Signal should be cleaned up
    assert "test_wf_ttl" not in builder._pending_stop_regen

    builder._pending_stop_regen.clear()


def test_node_completed_event_includes_io_fields():
    """node.completed event payload should include input_prompt and output_result fields.

    Phase 6B split: io_data construction lives in node_factory.py now; the
    macro_graph.py shim re-exports the public class but does not contain
    the literal source.
    """
    import inspect
    from harness.engine import node_factory
    source = inspect.getsource(node_factory)
    assert '"input_prompt"' in source, "node.completed event must include input_prompt field"
    assert '"output_result"' in source, "node.completed event must include output_result field"
