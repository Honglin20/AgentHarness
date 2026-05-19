from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import StdioServerParameters
from mcp.types import ListToolsResult, Tool as McpTool

from harness.tools.mcp_bridge import McpBridge, McpServerConfig, McpToolFactory
from harness.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# McpServerConfig
# ---------------------------------------------------------------------------


class TestMcpServerConfig:
    def test_defaults(self):
        cfg = McpServerConfig(command="node")
        assert cfg.name == ""
        assert cfg.command == "node"
        assert cfg.args == []
        assert cfg.env == {}

    def test_with_prefix(self):
        cfg = McpServerConfig(name="github", command="npx", args=["-y", "@modelcontextprotocol/server-github"])
        assert cfg.name == "github"
        assert cfg.args == ["-y", "@modelcontextprotocol/server-github"]

    def test_tool_name_with_prefix(self):
        cfg = McpServerConfig(name="github", command="npx")
        assert cfg.tool_name("create_pr") == "github_create_pr"

    def test_tool_name_without_prefix(self):
        cfg = McpServerConfig(command="npx")
        assert cfg.tool_name("read_file") == "read_file"

    def test_to_stdio_params(self):
        cfg = McpServerConfig(
            command="node",
            args=["server.js"],
            env={"API_KEY": "secret"},
        )
        params = cfg.to_stdio_params()
        assert isinstance(params, StdioServerParameters)
        assert params.command == "node"
        assert params.args == ["server.js"]
        assert params.env == {"API_KEY": "secret"}

    def test_to_stdio_params_empty_env(self):
        cfg = McpServerConfig(command="node")
        params = cfg.to_stdio_params()
        assert params.env is None


# ---------------------------------------------------------------------------
# McpToolFactory
# ---------------------------------------------------------------------------


class TestMcpToolFactory:
    def test_create_returns_pydantic_ai_tool(self):
        mock_session = AsyncMock()
        factory = McpToolFactory(
            session=mock_session,
            mcp_tool_name="search",
            registered_name="github_search",
            description="Search GitHub repos",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        tool = factory.create()
        assert tool.name == "github_search"
        assert tool.description == "Search GitHub repos"

    @pytest.mark.asyncio
    async def test_factory_tool_call_invokes_session(self):
        mock_session = AsyncMock()

        # Build a fake MCP call_tool result with text content
        text_block = MagicMock()
        text_block.text = "result text"
        mock_result = MagicMock()
        mock_result.content = [text_block]
        mock_session.call_tool.return_value = mock_result

        factory = McpToolFactory(
            session=mock_session,
            mcp_tool_name="search",
            registered_name="github_search",
            description="Search GitHub repos",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        tool = factory.create()

        # Simulate calling the inner function
        ctx = MagicMock()
        output = await tool.function(ctx, query="test")
        mock_session.call_tool.assert_awaited_once_with("search", arguments={"query": "test"})
        assert output == "result text"


# ---------------------------------------------------------------------------
# McpBridge
# ---------------------------------------------------------------------------


class TestMcpBridge:
    def test_tools_property_empty(self):
        registry = ToolRegistry()
        cfg = McpServerConfig(command="node")
        bridge = McpBridge(cfg, registry)
        assert bridge.tools == []

    @pytest.mark.asyncio
    async def test_register_tools_raises_without_connect(self):
        registry = ToolRegistry()
        cfg = McpServerConfig(command="node")
        bridge = McpBridge(cfg, registry)
        with pytest.raises(RuntimeError, match="Not connected"):
            await bridge.register_tools()

    @pytest.mark.asyncio
    async def test_connect_and_register_tools(self):
        registry = ToolRegistry()
        cfg = McpServerConfig(name="gh", command="npx")
        bridge = McpBridge(cfg, registry)

        # Build fake MCP tools
        fake_tool = McpTool(
            name="create_issue",
            description="Create an issue",
            inputSchema={"type": "object", "properties": {"title": {"type": "string"}}},
        )
        list_result = ListToolsResult(tools=[fake_tool])

        # Mock the session directly (bypass connect)
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_result)
        mock_session.__aexit__ = AsyncMock()

        # Set internal state directly
        bridge._session = mock_session
        bridge._session_cm = AsyncMock()
        bridge._stdio_cm = AsyncMock()

        # Register tools
        registered = await bridge.register_tools()
        assert registered == ["gh_create_issue"]
        assert bridge.tools == ["gh_create_issue"]
        assert "gh_create_issue" in registry.list_tools()

    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self):
        registry = ToolRegistry()
        cfg = McpServerConfig(command="node")
        bridge = McpBridge(cfg, registry)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aexit__ = AsyncMock()
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aexit__ = AsyncMock()

        bridge._session_cm = mock_session_cm
        bridge._stdio_cm = mock_stdio_cm
        bridge._session = MagicMock()

        await bridge.disconnect()
        mock_session_cm.__aexit__.assert_awaited_once_with(None, None, None)
        mock_stdio_cm.__aexit__.assert_awaited_once_with(None, None, None)
        assert bridge._session is None

    @pytest.mark.asyncio
    async def test_disconnect_noop_when_not_connected(self):
        registry = ToolRegistry()
        cfg = McpServerConfig(command="node")
        bridge = McpBridge(cfg, registry)
        # Should not raise
        await bridge.disconnect()
