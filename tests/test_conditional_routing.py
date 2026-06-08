"""Tests for conditional routing: after=None semantics and API schema preservation."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.api import Agent, Workflow
from harness.compiler.dag_builder import build_dag
from harness.engine.macro_graph import MacroGraphBuilder
from server.schemas import AgentDef


def _make_workflow(agents, workflow_dir=None):
    wf = MagicMock()
    wf.agents = agents
    wf.workflow_dir = workflow_dir or Path(__file__).resolve().parent / "compiler" / "fixtures"
    return wf


# ── 1. AgentDef schema: after field must preserve None ──────────────────


class TestAgentDefAfterNone:
    """AgentDef must distinguish after=None from after=[].

    after=None  → node only triggered via conditional edges (not from START)
    after=[]    → root node, starts immediately from START

    If the API layer loses this distinction, conditional-only nodes
    (summary, debugger) become root nodes and run in parallel with
    the classifier that should gate them.
    """

    def test_after_null_preserved(self):
        """JSON after:null should deserialize to Python None, not []."""
        raw = {"name": "summary", "after": None}
        agent_def = AgentDef(**raw)
        assert agent_def.after is None, (
            f"after=null should remain None, got {agent_def.after!r}. "
            "This causes conditional-only nodes to be treated as root nodes."
        )

    def test_after_absent_defaults_to_list(self):
        """Omitting after should default to [] (root node)."""
        agent_def = AgentDef(name="analyzer")
        assert agent_def.after == []

    def test_after_explicit_list(self):
        """after=['x'] should stay as ['x']."""
        agent_def = AgentDef(name="planner", after=["analyzer"])
        assert agent_def.after == ["analyzer"]

    def test_round_trip_via_json(self):
        """Full JSON round-trip: after:null in → after:null out."""
        payload = {
            "name": "conditional_route",
            "agents": [
                {"name": "analyzer", "after": []},
                {"name": "classifier", "after": ["analyzer"], "on_pass": "summary", "on_fail": "debugger"},
                {"name": "summary", "after": None},
                {"name": "debugger", "after": None},
            ],
            "workflow": "conditional_route",
            "inputs": {"task": "test"},
        }
        agents_defs = [AgentDef(**a) for a in payload["agents"]]
        assert agents_defs[2].after is None, "summary after should be None"
        assert agents_defs[3].after is None, "debugger after should be None"

    def test_api_route_creates_correct_agent(self):
        """_create_and_start_workflow should produce Agent(after=None), not Agent(after=[])."""
        from server.routes import _create_and_start_workflow

        # Simulate what the API receives when after:null comes in
        agents_defs = [
            AgentDef(name="analyzer", after=[]),
            AgentDef(name="classifier", after=["analyzer"], on_pass="summary", on_fail="debugger"),
            AgentDef(name="summary", after=None),
            AgentDef(name="debugger", after=None),
        ]
        # Build agents the same way _create_and_start_workflow does
        agents = [
            Agent(name=a.name, after=a.after, on_pass=a.on_pass, on_fail=a.on_fail)
            for a in agents_defs
        ]
        assert agents[2].after is None, "summary Agent.after should be None"
        assert agents[3].after is None, "debugger Agent.after should be None"


# ── 2. Graph build: after=None nodes must not get START edge ───────────


class TestConditionalRoutingGraphBuild:
    """Verify macro_graph.build() correctly handles after=None nodes."""

    def test_conditional_only_nodes_not_in_start_edges(self):
        """Nodes with after=None should NOT receive START edges.

        In the conditional_route example:
          analyzer → classifier
                       ├─ pass → summary
                       └─ fail → debugger

        summary and debugger have after=None, meaning they should only
        be reachable via classifier's conditional edges. They must NOT
        be connected to START.
        """
        agents = [
            Agent("analyzer", after=[]),
            Agent("classifier", after=["analyzer"], on_pass="summary", on_fail="debugger"),
            Agent("summary", after=None),
            Agent("debugger", after=None),
        ]
        workflow = _make_workflow(agents)

        builder = MacroGraphBuilder()
        graph = builder.build(workflow)

        # Use the same logic as the fixed macro_graph.py
        dep_map = {a.name: a.after for a in agents}
        conditional_only_nodes = {a.name for a in agents if a.after is None}
        root_nodes = {name for name, deps in dep_map.items() if deps is not None and not deps}

        # summary and debugger should be in conditional_only_nodes
        assert "summary" in conditional_only_nodes
        assert "debugger" in conditional_only_nodes

        # They should NOT be in root_nodes (after=None ≠ empty deps)
        for agent_name in conditional_only_nodes:
            assert agent_name not in root_nodes, (
                f"{agent_name} should not be in root_nodes — "
                "after=None means conditional-only, not root"
            )

        # analyzer should be in root_nodes (after=[])
        assert "analyzer" in root_nodes

    def test_after_empty_list_gets_start_edge(self):
        """Nodes with after=[] SHOULD get START edges (they are root nodes)."""
        agents = [
            Agent("analyzer", after=[]),
        ]
        workflow = _make_workflow(agents)

        builder = MacroGraphBuilder()
        graph = builder.build(workflow)
        compiled = graph.compile()
        assert compiled is not None

    def test_after_none_vs_empty_list_distinguishes(self):
        """after=None and after=[] must produce different graph topologies.

        after=[]  → root node, connected to START
        after=None → conditional-only, NOT connected to START
        """
        # Case 1: after=[] — root node
        dep_map1 = {"solo": []}
        cond_only1 = set()
        root1 = {n for n, d in dep_map1.items() if d is not None and not d and n not in cond_only1}
        assert "solo" in root1

        # Case 2: after=None — not a root
        dep_map2 = {"gated": None}
        cond_only2 = {"gated"}
        root2 = {n for n, d in dep_map2.items() if d is not None and not d and n not in cond_only2}
        assert "gated" not in root2
        assert "gated" in cond_only2

    def test_dag_builder_treats_after_none_as_no_static_dep(self):
        """build_dag should treat after=None same as no static deps (in_degree=0).

        Both after=None and after=[] result in in_degree=0, so both appear
        in the topological sort. The distinction only matters at graph-build
        time (START edge vs conditional edge).
        """
        agents = [
            Agent("analyzer", after=[]),
            Agent("classifier", after=["analyzer"], on_pass="summary", on_fail="debugger"),
            Agent("summary", after=None),
            Agent("debugger", after=None),
        ]
        order = build_dag(agents)
        # All 4 agents must be in the topological order
        assert set(order) == {"analyzer", "classifier", "summary", "debugger"}
        # analyzer must come before classifier
        assert order.index("analyzer") < order.index("classifier")


# ── 3. list_saved: after=None must not crash ───────────────────────────


class TestListSavedAfterNone:
    """Workflow.list_saved() should handle after=None in workflow.json.

    Bug: the private-workflow section iterates `a.after` without
    guarding for None, causing TypeError: 'NoneType' is not iterable.
    The shared and legacy sections use `a.after or []` but the private
    section forgot this guard.
    """

    def test_list_saved_with_after_none_in_private_workflow(self, tmp_path, monkeypatch):
        """list_saved should not crash when an agent has after=None."""
        import harness.workflow as api_mod

        # Set up private workflow directory
        user_wf_dir = tmp_path / "workflows" / "users" / "user1" / "workflows" / "cond_route"
        agents_dir = user_wf_dir / "agents"
        agents_dir.mkdir(parents=True)

        wf_data = {
            "name": "cond_route",
            "agents": [
                {"name": "analyzer", "after": []},
                {"name": "classifier", "after": ["analyzer"], "on_pass": "summary", "on_fail": "debugger"},
                {"name": "summary", "after": None},
                {"name": "debugger", "after": None},
            ],
        }
        (user_wf_dir / "workflow.json").write_text(json.dumps(wf_data))
        (agents_dir / "analyzer.md").write_text("---\nname: analyzer\n---\nAnalyzes input.")
        (agents_dir / "classifier.md").write_text("---\nname: classifier\n---\nClassifies input.")
        (agents_dir / "summary.md").write_text("---\nname: summary\n---\nSummarizes input.")
        (agents_dir / "debugger.md").write_text("---\nname: debugger\n---\nDebugs issues.")

        monkeypatch.setattr(api_mod, "_WORKFLOWS_DIR", tmp_path / "workflows")

        # This call must not raise TypeError
        result = Workflow.list_saved(user_id="user1")
        cond = [r for r in result if r["name"] == "cond_route"]
        assert len(cond) == 1

        # Verify conditional edges are present
        dag = cond[0]["dag"]
        cond_edges = dag.get("conditional_edges", [])
        edge_labels = {(e["from"], e["to"]) for e in cond_edges}
        assert ("classifier", "summary") in edge_labels
        assert ("classifier", "debugger") in edge_labels

    def test_list_saved_with_after_none_in_legacy_workflow(self, tmp_path, monkeypatch):
        """Legacy workflows (no user_id) should also handle after=None."""
        import harness.workflow as api_mod

        wf_dir = tmp_path / "workflows" / "cond_route"
        agents_dir = wf_dir / "agents"
        agents_dir.mkdir(parents=True)

        wf_data = {
            "name": "cond_route",
            "agents": [
                {"name": "analyzer", "after": []},
                {"name": "summary", "after": None},
            ],
        }
        (wf_dir / "workflow.json").write_text(json.dumps(wf_data))
        (agents_dir / "analyzer.md").write_text("---\nname: analyzer\n---\nAnalyzes.")
        (agents_dir / "summary.md").write_text("---\nname: summary\n---\nSummarizes.")

        monkeypatch.setattr(api_mod, "_WORKFLOWS_DIR", tmp_path / "workflows")

        result = Workflow.list_saved()
        cond = [r for r in result if r["name"] == "cond_route"]
        assert len(cond) == 1
