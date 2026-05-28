"""Quick MCP connectivity test — connects, lists tools, calls one.

Usage:
    python check_mcp.py
"""

import asyncio
import sys

print("AgentHarness — MCP Server Check\n")

# ── 1. Check binary availability ────────────────────────────────
from harness.tools.defaults import _find_filesystem_server

binary = _find_filesystem_server()
if binary:
    print(f"  Binary:     ✓ {binary}")
else:
    print("  Binary:     ⚠ not found, falling back to npx")

# ── 2. Connect & list tools ─────────────────────────────────────
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry


async def main() -> None:
    workdir = "."
    if binary:
        config = McpServerConfig(name="", command=binary, args=[workdir])
    else:
        config = McpServerConfig(
            name="",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", workdir],
        )

    print(f"  Command:    {config.command} {' '.join(config.args)}")
    print()

    registry = ToolRegistry()
    bridge = McpBridge(config, registry=registry)

    try:
        print("  Connecting ...")
        await bridge.connect()
        print("  Connection: ✓")

        print("  Listing tools ...")
        tools = await bridge.register_tools()
        print(f"  Tools:      ✓ {len(tools)} found")
        for t in tools:
            print(f"              - {t}")

        # ── 3. Call a simple tool ────────────────────────────────
        if "list_directory" in tools:
            print("\n  Calling list_directory('.') ...")
            result = await bridge._session.call_tool("list_directory", arguments={"path": "."})
            entries = [b.text for b in result.content if isinstance(b.text, str)]
            # entries come as JSON string in a single block
            text = "\n".join(entries)
            lines = [l for l in text.splitlines() if l.strip()]
            print(f"  Call:       ✓ returned {len(lines)} entries")
            for line in lines[:5]:
                print(f"              {line}")
            if len(lines) > 5:
                print(f"              ... ({len(lines) - 5} more)")
        else:
            print("\n  (list_directory not available, skipping tool call)")

    except FileNotFoundError:
        print("  ✗ Server binary not found — install with:")
        print("    npm install -g @modelcontextprotocol/server-filesystem")
        sys.exit(1)
    except Exception as e:
        msg = str(e).lower()
        if "timeout" in msg or "connect" in msg:
            print(f"  ✗ Connection timeout — check network / binary")
        elif "spawn" in msg or "enoent" in msg:
            print(f"  ✗ Cannot start server — binary or npx not found")
        else:
            print(f"  ✗ Error: {e}")
        sys.exit(1)
    finally:
        await bridge.disconnect()

    print("\n✓ MCP connection works.")


asyncio.run(main())
