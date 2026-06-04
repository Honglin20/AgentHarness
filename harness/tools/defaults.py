from __future__ import annotations

import shutil
from pathlib import Path

from harness.tools.bash import BashToolFactory
from harness.tools.grep_glob import GrepToolFactory, GlobToolFactory
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory
from harness.tools.chart import render_chart, RenderChartToolFactory


def _find_filesystem_server(
    extra_candidates: list[str | Path] | None = None,
) -> str | None:
    """Find the filesystem MCP server binary.

    Search order:
      1. extra_candidates (caller overrides)
      2. $PATH (``which mcp-server-filesystem``)
      3. Common install locations
      4. Returns None → caller falls back to ``npx``
    """
    # 1. Caller overrides
    for p in (extra_candidates or []):
        if Path(p).exists():
            return str(p)

    # 2. On $PATH
    found = shutil.which("mcp-server-filesystem")
    if found:
        return found

    # 3. Common install locations not on PATH
    for p in [
        Path.home() / ".local/bin/mcp-server-filesystem",
        Path("/tmp/mcp-servers/node_modules/.bin/mcp-server-filesystem"),
    ]:
        if p.exists():
            return str(p)

    return None


def default_tool_registry(event_bus=None) -> ToolRegistry:
    """创建默认工具注册表：sub_agent + bash 自建工具

    Args:
        event_bus: Optional EventBus. When provided, registers event-bus-dependent
            tools (ask_user).
    """
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    registry.register("bash", BashToolFactory())
    registry.register("grep", GrepToolFactory())
    registry.register("glob", GlobToolFactory())
    registry.register("render_chart", RenderChartToolFactory(event_bus=event_bus))
    if event_bus:
        from harness.tools.ask_user import AskUserToolFactory
        registry.register("ask_user", AskUserToolFactory(event_bus=event_bus))

    from harness.tools.dedup_guard import configure_dedup
    configure_dedup(window_ms=5)

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


async def setup_codegraph_mcp(
    registry: ToolRegistry,
    path: str | None = None,
) -> McpBridge | None:
    """Connect codegraph MCP server and register its tools.

    codegraph is a local code-intelligence index (search / context / callers /
    callees / impact / node / explore / status / files / trace) backed by a
    per-project sqlite DB in ``.codegraph/``. Tools register as
    ``codegraph_<name>`` since the upstream MCP server already namespaces them
    that way — no extra prefix needed.

    Args:
        registry: Tool registry to register MCP tools into.
        path: Project path the codegraph server should operate on. When None,
            the server uses the directory it was launched from. Pass an
            absolute path when you want code-graph queries scoped to a
            different project than the workflow's working directory.

    Resolution:
      1. ``codegraph`` on $PATH → run ``codegraph serve --mcp`` directly
      2. Not on PATH → fall back to ``npx -y @colbymchenry/codegraph serve --mcp``
         (npx will install the package on first use)

    Returns the bridge, or None if startup failed (caller logs the hint).
    """
    base_args = ["serve", "--mcp"]
    if path:
        base_args += ["-p", path]

    command = shutil.which("codegraph")
    if command is not None:
        config = McpServerConfig(name="", command=command, args=base_args)
    else:
        # Fall back to npx — first invocation will install the package
        config = McpServerConfig(
            name="",
            command="npx",
            args=["-y", "@colbymchenry/codegraph", *base_args],
        )

    bridge = McpBridge(config, registry=registry)
    await bridge.connect()
    await bridge.register_tools()
    return bridge
