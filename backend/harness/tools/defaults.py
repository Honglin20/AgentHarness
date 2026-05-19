from __future__ import annotations

import shutil
from pathlib import Path

from harness.tools.bash import BashToolFactory
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory


def _find_filesystem_server() -> str:
    """Find the filesystem MCP server binary path."""
    # Check common locations
    candidates = [
        Path("/tmp/mcp-servers/node_modules/.bin/mcp-server-filesystem"),
        Path.home() / ".local/bin/mcp-server-filesystem",
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    # Fall back to npx
    return "npx"


DEFAULT_MCP_SERVERS = [
    McpServerConfig(
        name="",
        command=_find_filesystem_server(),
        args=["."],  # workdir injected by setup_default_mcp
        # When using npx, command="npx" and args=["-y", "@modelcontextprotocol/server-filesystem", "."]
    ),
    # bash 自建为 BashToolFactory，不通过 MCP
]


def default_tool_registry() -> ToolRegistry:
    """创建默认工具注册表：sub_agent + bash 自建工具"""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    registry.register("bash", BashToolFactory())
    return registry


async def setup_default_mcp(registry: ToolRegistry, workdir: str = ".") -> list[McpBridge]:
    """连接默认 MCP Server 并注册工具"""
    bridges = []
    for config in DEFAULT_MCP_SERVERS:
        # Inject workdir into filesystem server args
        if "server-filesystem" in config.command or config.command != "npx":
            # Direct binary: args = [workdir]
            effective_config = config.model_copy(update={
                "args": [workdir],
            })
        else:
            # npx: args = ["-y", "@modelcontextprotocol/server-filesystem", workdir]
            effective_config = config.model_copy(update={
                "args": config.args[:-1] + [workdir],
            })

        bridge = McpBridge(effective_config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()
        bridges.append(bridge)
    return bridges
