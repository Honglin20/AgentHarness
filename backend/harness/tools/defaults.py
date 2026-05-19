from __future__ import annotations

from harness.tools.bash import BashToolFactory
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory

DEFAULT_MCP_SERVERS = [
    McpServerConfig(
        name="",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
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
        if "server-filesystem" in str(config.args):
            effective_config = config.model_copy(update={
                "args": config.args[:-1] + [workdir],
            })
        else:
            effective_config = config

        bridge = McpBridge(effective_config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()
        bridges.append(bridge)
    return bridges
