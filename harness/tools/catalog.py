"""ToolCatalogService — pre-connects MCP servers to build a full tool catalog."""

from __future__ import annotations

import logging
import sys
from typing import Any

from harness.tools.defaults import default_tool_registry, setup_default_mcp, setup_codegraph_mcp
from harness.tools.mcp_bridge import McpBridge
from harness.tools.registry import ToolCatalogEntry, ToolRegistry

logger = logging.getLogger(__name__)


class ToolCatalogService:
    """Connects all default MCP servers at startup and caches the full tool catalog.

    Usage:
        catalog = ToolCatalogService()
        await catalog.refresh(workdir=".")
        entries = catalog.get_catalog()     # list[ToolCatalogEntry]
        await catalog.cleanup()
    """

    def __init__(self) -> None:
        self._catalog: list[ToolCatalogEntry] = []
        self._registry: ToolRegistry | None = None
        self._bridges: list[McpBridge] = []

    async def refresh(self, workdir: str = ".", codegraph_path: str | None = None) -> None:
        """Build the full catalog by connecting default MCP servers.

        Builds a fresh ToolRegistry with built-in tools + filesystem MCP +
        codegraph MCP.  Failures to connect individual MCP servers are logged
        but do not block the catalog — the catalog will simply contain fewer
        tools.
        """
        # Cleanup previous connections first
        await self.cleanup()

        registry = default_tool_registry(event_bus=None)

        # Filesystem MCP
        try:
            bridges = await setup_default_mcp(registry, workdir=workdir)
            self._bridges.extend(bridges)
        except Exception as e:
            print(f"  [tool-catalog] filesystem MCP skipped: {e}", file=sys.stderr)

        # Codegraph MCP
        try:
            bridge = await setup_codegraph_mcp(registry, path=codegraph_path)
            if bridge:
                self._bridges.append(bridge)
        except Exception as e:
            print(f"  [tool-catalog] codegraph MCP skipped: {e}", file=sys.stderr)

        self._registry = registry
        self._catalog = registry.get_tool_catalog()

    def get_catalog(self) -> list[ToolCatalogEntry]:
        """Return the cached catalog entries."""
        return list(self._catalog)

    async def cleanup(self) -> None:
        """Disconnect all MCP bridges."""
        for bridge in self._bridges:
            try:
                await bridge.disconnect()
            except Exception:
                logger.exception("MCP bridge disconnect failed during catalog cleanup")
        self._bridges.clear()
        self._catalog = []
        self._registry = None
