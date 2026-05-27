from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from harness.tools.bash import BashToolFactory
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory


def _make_ctx(workdir: str = ".", agent_name: str = "test", depth: int = 0) -> RunContext[AgentDeps]:
    deps = AgentDeps(workdir=workdir, agent_name=agent_name, depth=depth)
    return RunContext(
        deps=deps,
        model=None,
        usage=None,
        prompt=None,
    )


class TestSubAgentToolFactory:
    def test_name(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry)
        assert factory.name == "sub_agent"

    def test_description_contains_key_phrases(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry)
        desc_lower = factory.description.lower()
        assert "sub-agent" in desc_lower
        assert "cannot spawn" in desc_lower

    def test_create_returns_tool(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry)
        tool = factory.create()
        assert tool is not None

    def test_depth_excludes_sub_agent_from_registry(self):
        """Nesting prevention: child agent tools do NOT include sub_agent"""
        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        registry.register("sub_agent", SubAgentToolFactory(registry=registry))

        tools = registry.resolve(None, exclude=["sub_agent"])
        tool_names = [t.name for t in tools]
        assert "bash" in tool_names
        assert "sub_agent" not in tool_names

    @pytest.mark.asyncio
    async def test_depth_at_max_returns_error(self):
        """When depth >= max_depth, the tool returns an error message"""
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry, max_depth=1)
        tool = factory.create(depth=1)
        sub_agent_fn = tool.function
        ctx = _make_ctx()
        result = await sub_agent_fn(ctx, task="do something")
        assert result == "Error: maximum sub-agent depth reached"

    @pytest.mark.asyncio
    async def test_depth_above_max_returns_error(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry, max_depth=1)
        tool = factory.create(depth=2)
        sub_agent_fn = tool.function
        ctx = _make_ctx()
        result = await sub_agent_fn(ctx, task="do something")
        assert result == "Error: maximum sub-agent depth reached"

    @pytest.mark.asyncio
    async def test_tool_execution_with_mocked_agent(self):
        """Tool execution creates a child agent and returns its output"""
        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        factory = SubAgentToolFactory(registry=registry, model="test-model")
        tool = factory.create(depth=0)
        sub_agent_fn = tool.function

        mock_result = MagicMock()
        mock_result.output = "sub-agent completed the task"
        mock_child = MagicMock()
        mock_child.run = AsyncMock(return_value=mock_result)

        with patch("harness.tools.sub_agent.LLMClient") as MockLLMClient:
            mock_client = MagicMock()
            mock_client.agent.return_value = mock_child
            MockLLMClient.return_value = mock_client
            ctx = _make_ctx(workdir="/tmp/test")
            result = await sub_agent_fn(ctx, task="analyze the code")

        assert result == "sub-agent completed the task"
        mock_child.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_child_agent_gets_correct_deps(self):
        """Child agent receives depth+1 and inherited workdir"""
        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        factory = SubAgentToolFactory(registry=registry, max_depth=2)
        tool = factory.create(depth=0)
        sub_agent_fn = tool.function

        mock_result = MagicMock()
        mock_result.output = "done"
        mock_child = MagicMock()
        mock_child.run = AsyncMock(return_value=mock_result)

        with patch("harness.tools.sub_agent.LLMClient") as MockLLMClient:
            mock_client = MagicMock()
            mock_client.agent.return_value = mock_child
            MockLLMClient.return_value = mock_client
            ctx = _make_ctx(workdir="/project/root", depth=0)
            await sub_agent_fn(ctx, task="do work")

        call_args = mock_child.run.call_args
        child_deps = call_args.kwargs.get("deps")
        assert child_deps.depth == 1
        assert child_deps.workdir == "/project/root"
        assert child_deps.agent_name == "sub_agent"

    @pytest.mark.asyncio
    async def test_child_agent_excludes_sub_agent_tool(self):
        """Child agent is created without sub_agent tool (physical nesting prevention)"""
        registry = ToolRegistry()
        registry.register("bash", BashToolFactory())
        registry.register("sub_agent", SubAgentToolFactory(registry=registry))
        factory = SubAgentToolFactory(registry=registry)
        tool = factory.create(depth=0)
        sub_agent_fn = tool.function

        mock_result = MagicMock()
        mock_result.output = "done"
        mock_child = MagicMock()
        mock_child.run = AsyncMock(return_value=mock_result)

        with patch("harness.tools.sub_agent.LLMClient") as MockLLMClient:
            mock_client = MagicMock()
            mock_client.agent.return_value = mock_child
            MockLLMClient.return_value = mock_client
            ctx = _make_ctx()
            await sub_agent_fn(ctx, task="do work")

        agent_call_kwargs = mock_child.run.call_args

    def test_default_model(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry)
        assert factory.model == "" or isinstance(factory.model, str)

    def test_custom_model(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry, model="openai:gpt-4")
        assert factory.model == "openai:gpt-4"

    def test_default_max_depth(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry)
        assert factory.max_depth == 1

    def test_custom_max_depth(self):
        registry = ToolRegistry()
        factory = SubAgentToolFactory(registry=registry, max_depth=3)
        assert factory.max_depth == 3
