from __future__ import annotations

from pathlib import Path

from harness.tools.bash import BashToolFactory
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory
from harness.tools.chart import render_chart


def _find_filesystem_server(
    extra_candidates: list[str | Path] | None = None,
) -> str | None:
    """Find the filesystem MCP server binary path.

    Returns None if not found — caller should fall back to npx.
    """
    candidates = [
        *(Path(p) for p in (extra_candidates or [])),
        Path("/tmp/mcp-servers/node_modules/.bin/mcp-server-filesystem"),
        Path.home() / ".local/bin/mcp-server-filesystem",
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    return None


def default_tool_registry(event_bus=None) -> ToolRegistry:
    """创建默认工具注册表：sub_agent + bash 自建工具

    Args:
        event_bus: Optional EventBus. When provided, registers event-bus-dependent
            tools (ask_human).
    """
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    registry.register("bash", BashToolFactory())
    if event_bus:
        from harness.tools.ask_human import AskHumanToolFactory
        registry.register("ask_human", AskHumanToolFactory(event_bus=event_bus))
    return registry


async def setup_default_mcp(
    registry: ToolRegistry,
    workdir: str = ".",
    server_path: str | None = None,
) -> list[McpBridge]:
    """连接默认 MCP Server 并注册工具

    Args:
        registry: Tool registry to register MCP tools into.
        workdir: Working directory for the filesystem server.
        server_path: Override filesystem server binary path.
            If None, uses the auto-discovered path.
    """
    command = server_path or _find_filesystem_server()

    if command is not None:
        # Binary found — just pass the workdir
        config = McpServerConfig(name="", command=command, args=[workdir])
    else:
        # Fall back to npx with the correct package name
        config = McpServerConfig(
            name="",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", workdir],
        )

    bridge = McpBridge(config, registry=registry)
    await bridge.connect()
    await bridge.register_tools()
    return [bridge]
