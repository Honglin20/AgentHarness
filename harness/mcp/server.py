"""stdio MCP server (claude 子进程) — 转发 tools/call 到主进程 unix socket。

由 claude 通过 ``--mcp-config`` spawn。启动时通过环境变量
``HARNESS_MCP_SOCKET_PATH`` 找到主进程的 McpProxyServer socket 路径。

协议流（与 harness/mcp/proxy.py 配套）:
  claude → stdin JSON-RPC → 本 server → unix socket McpCallRequest → 主进程
  主进程 handler → McpCallResponse → 本 server → stdout JSON-RPC → claude

工具列表 (TOOLS): Phase D.1 只 ``ping``；Phase D.5 起 ``register_default_handlers``
同步加 ask_user / TodoTool / render_chart，**本模块的 TOOLS 必须与主进程
_HANDLERS 注册的 handler 一一对应**（idempotent: 子进程拿不到主进程 handler
列表，所以 hardcode；新增工具 = 改两个地方 + 加测试）。

详细设计: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §7
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from harness.mcp.protocol import (
    PROTOCOL_VERSION,
    McpCallRequest,
    McpCallResponse,
)
from harness.mcp.handlers import ASK_USER_TOOL_DEFINITION

logger = logging.getLogger(__name__)

SOCKET_PATH_ENV = "HARNESS_MCP_SOCKET_PATH"

# 静态工具列表 — 必须与主进程 _HANDLERS 一一对应（见模块 docstring）。
# 加新工具 = 在 harness/mcp/handlers/ 加 handler 模块 + 在这里 import TOOL_DEFINITION
# + 在 proxy.register_default_handlers() 注册。
TOOLS: list[dict[str, Any]] = [
    {
        "name": "ping",
        "description": (
            "Echo back text via IPC to the harness main process. "
            "Used for smoke testing the MCP bridge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    ASK_USER_TOOL_DEFINITION,
]


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------


def _send_jsonrpc(obj: dict) -> None:
    """写一行 JSON-RPC 到 stdout（claude 读）。"""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _make_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# IPC client (本 server → 主进程 proxy)
# ---------------------------------------------------------------------------


async def _forward_call_to_proxy(
    socket_path: str, req_id: int, name: str, arguments: dict[str, Any]
) -> McpCallResponse:
    """开 socket 连接主进程，发 McpCallRequest，等 McpCallResponse。

    每次都新开连接（简化协议；MCP server 生命周期内 tools/call 频率低）。
    """
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        req = McpCallRequest(request_id=req_id, tool_name=name, arguments=arguments)
        writer.write((req.to_json_line() + "\n").encode("utf-8"))
        await writer.drain()

        line = await reader.readline()
        if not line:
            raise RuntimeError("proxy closed connection without response")
        return McpCallResponse.from_json_line(line.decode("utf-8"))
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# JSON-RPC method handlers
# ---------------------------------------------------------------------------


async def _handle_initialize(req_id: Any) -> None:
    _send_jsonrpc(_make_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": "harness-mcp", "version": "0.1.0"},
        "capabilities": {"tools": {"listChanged": False}},
    }))


def _handle_initialized_notification() -> None:
    # notification, no response (sent by claude after initialize completes)
    pass


def _handle_tools_list(req_id: Any) -> None:
    _send_jsonrpc(_make_response(req_id, {"tools": TOOLS}))


async def _handle_tools_call(
    req_id: Any, params: dict, socket_path: str
) -> None:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not name:
        _send_jsonrpc(_make_response(req_id, {
            "content": [{"type": "text", "text": "missing tool name"}],
            "isError": True,
        }))
        return

    try:
        resp = await _forward_call_to_proxy(socket_path, int(req_id) if req_id is not None else 0, name, arguments)
    except Exception as e:
        logger.exception("IPC forward failed for tool %s", name)
        _send_jsonrpc(_make_response(req_id, {
            "content": [{"type": "text", "text": f"IPC error: {type(e).__name__}: {e}"}],
            "isError": True,
        }))
        return

    _send_jsonrpc(_make_response(req_id, {
        "content": resp.content,
        "isError": resp.is_error,
    }))


def _handle_unknown_method(req_id: Any, method: str) -> None:
    if req_id is None:
        return  # unknown notification, ignore
    _send_jsonrpc(_make_error(req_id, -32601, f"method not found: {method}"))


# ---------------------------------------------------------------------------
# Stdin reader
# ---------------------------------------------------------------------------


async def _read_stdin_lines() -> asyncio.StreamReader:
    """把 sys.stdin 包装成 asyncio StreamReader（按行读）。"""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    # Windows 不支持 connect_read_pipe；本项目 darwin/linux，OK
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return reader


async def _serve(socket_path: str) -> None:
    reader = await _read_stdin_lines()
    logger.info("harness-mcp server ready; socket=%s", socket_path)

    while True:
        try:
            line_bytes = await reader.readline()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stdin read failed; exiting")
            break

        if not line_bytes:
            # EOF: claude 关闭了 stdin，正常退出
            logger.info("stdin EOF; harness-mcp server exiting")
            break

        line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
        if not line.strip():
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning("malformed JSON-RPC line: %r err=%s", line[:200], e)
            continue

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}

        try:
            if method == "initialize":
                await _handle_initialize(req_id)
            elif method == "notifications/initialized":
                _handle_initialized_notification()
            elif method == "tools/list":
                _handle_tools_list(req_id)
            elif method == "tools/call":
                await _handle_tools_call(req_id, params, socket_path)
            elif method in ("resources/list", "prompts/list"):
                # 空响应 — claude probe 用
                _send_jsonrpc(_make_response(req_id, {"resources": []} if method == "resources/list" else {"prompts": []}))
            else:
                _handle_unknown_method(req_id, method or "<missing>")
        except Exception:
            logger.exception("error handling method=%s id=%s", method, req_id)
            if req_id is not None:
                _send_jsonrpc(_make_error(req_id, -32603, "internal error"))


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> int:
    """python -m harness.mcp.server entry point."""
    socket_path = os.environ.get(SOCKET_PATH_ENV)
    if not socket_path:
        sys.stderr.write(
            f"ERROR: ${SOCKET_PATH_ENV} env var not set; cannot connect to harness proxy\n"
        )
        return 2

    try:
        asyncio.run(_serve(socket_path))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
