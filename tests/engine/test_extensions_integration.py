"""P1 integration tests for hook/middleware/mutator wiring in macro_graph.

These do NOT call any LLM. They verify the scaffolding compiles cleanly:
  - GraphMutator can append agents to a workflow before build
  - Bus is wired into MacroGraphBuilder
  - Existing event emission behavior is unchanged when registry is empty
"""

from __future__ import annotations

import pytest

from harness.api import Agent, Workflow
from harness.engine.macro_graph import MacroGraphBuilder
from harness.extensions import BaseGraphMutator
from harness.extensions.bus import Bus
from harness.tools.registry import ToolRegistry


@pytest.fixture
def two_agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "a.md").write_text("---\nname: a\nretries: 0\n---\nA agent.\n")
    (d / "b.md").write_text("---\nname: b\nretries: 0\n---\nB agent.\n")
    return d


def test_graph_mutator_appends_agent(two_agents_dir):
    """GraphMutator runs at build time and its added agents become DAG nodes."""

    class AppendC(BaseGraphMutator):
        name = "append_c"
        def mutate(self, workflow: Workflow) -> Workflow:
            # Add agent 'c' after 'b'. Write its md file too.
            (two_agents_dir / "c.md").write_text("---\nname: c\nretries: 0\n---\nC agent.\n")
            workflow.agents.append(Agent("c", after=["b"]))
            return workflow

    bus = Bus()
    bus.register(AppendC())

    wf = Workflow(
        name="t",
        agents=[Agent("a", after=[]), Agent("b", after=["a"])],
        agents_dir=str(two_agents_dir),
        event_bus=bus,
        tool_registry=ToolRegistry(),
    )

    graph = wf.compile()  # triggers MacroGraphBuilder.build → mutators
    assert graph is not None

    # Verify the mutator's agent is now in the workflow
    names = {a.name for a in wf.agents}
    assert names == {"a", "b", "c"}


def test_mutator_exception_propagates_from_compile(two_agents_dir):
    """A buggy mutator aborts compile (fail-loud, per SPEC)."""

    class Boom(BaseGraphMutator):
        name = "boom"
        def mutate(self, workflow):
            raise RuntimeError("intentional")

    bus = Bus()
    bus.register(Boom())

    wf = Workflow(
        name="t",
        agents=[Agent("a", after=[])],
        agents_dir=str(two_agents_dir),
        event_bus=bus,
        tool_registry=ToolRegistry(),
    )
    with pytest.raises(RuntimeError, match="intentional"):
        wf.compile()


def test_empty_extension_registry_unchanged_compile(two_agents_dir):
    """When no extensions are registered, build behaves identically."""
    bus = Bus()  # empty
    wf = Workflow(
        name="t",
        agents=[Agent("a", after=[]), Agent("b", after=["a"])],
        agents_dir=str(two_agents_dir),
        event_bus=bus,
        tool_registry=ToolRegistry(),
    )
    graph = wf.compile()
    assert graph is not None


def test_workflow_use_returns_self_and_registers(two_agents_dir):
    """Workflow.use() registers extensions and supports fluent chaining."""
    from harness.extensions.compact import AutoCompact

    wf = Workflow(
        name="t",
        agents=[Agent("a", after=[])],
        agents_dir=str(two_agents_dir),
        tool_registry=ToolRegistry(),
    )
    result = wf.use(AutoCompact(threshold_tokens=1000, summarizer=lambda t: __import__("asyncio").sleep(0)))
    assert result is wf  # fluent
    assert wf._event_bus is not None
    # AutoCompact registered as middleware
    assert "auto_compact" in wf._event_bus._middleware


def test_workflow_use_chains_multiple(two_agents_dir):
    from harness.extensions.compact import AutoCompact
    from harness.extensions import BaseHook

    class L(BaseHook):
        name = "logger"

    wf = (
        Workflow("t", [Agent("a", after=[])], agents_dir=str(two_agents_dir), tool_registry=ToolRegistry())
        .use(AutoCompact(threshold_tokens=1000))
        .use(L())
    )
    assert "auto_compact" in wf._event_bus._middleware
    assert "logger" in wf._event_bus._hooks
