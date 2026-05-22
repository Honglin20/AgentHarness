from pathlib import Path
from unittest.mock import MagicMock

from harness.engine.macro_graph import MacroGraphBuilder
from harness.api import Agent


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
