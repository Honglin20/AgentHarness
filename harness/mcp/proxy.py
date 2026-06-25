"""主进程内 MCP proxy — unix socket server + handler dispatch。

主进程（harness）在 ClaudeCodeExecutor.run() 之前启动一个 ``McpProxyServer``：
  1. 监听一个临时 unix socket path（如 ``/tmp/harness-mcp-<run_id>.sock``）
  2. 接受 MCP server 子进程的连接
  3. 每收到一个 ``McpCallRequest`` 就按 ``tool_name`` dispatch 到 handler
  4. 把 handler 的返回值（``McpCallResponse``）写回 socket

handler 注册到本模块的 ``_HANDLERS`` dict；每个 handler 是 async callable，
签名: ``async def handler(arguments: dict, ctx: HandlerCtx) -> McpCallResponse``。

Phase D.1 只注册 ping（用于 e2e smoke test）；D.5 起注册 ask_user 等真实工具。

为什么不在主进程开 MCP server 直接给 claude:
  claude --mcp-config 自己 spawn 子进程，不能注入主进程的 fd；只能通过
  unix socket path 让独立子进程找到主进程。本模块就是那个"被找"的 server。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Any

from harness.mcp.protocol import McpCallRequest, McpCallResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------


@dataclass
class HandlerCtx:
    """Handler 调用上下文 — 把 proxy 知道的元数据传给 handler。

    Handler 拿到这些可以 emit event / 调用 _human_io 等。
    """

    workflow_id: str
    node_id: str
    agent_name: str
    event_bus: Any | None = None
    #: 额外上下文（如 run_id、session_dir 等），handler 按需读
    extra: dict[str, Any] = field(default_factory=dict)


HandlerFn = Callable[[dict[str, Any], HandlerCtx, int], Awaitable[McpCallResponse]]


# 全局 handler 注册表 — 名字 → handler 函数
# Phase D 用 module-level dict 而非类注册，简化测试和扩展。
# 加新工具 = 写 handler 函数 + 在 register_default_handlers() 注册。
_HANDLERS: dict[str, HandlerFn] = {}


def register_handler(name: str, fn: HandlerFn) -> None:
    """注册一个 MCP tool handler。同名覆盖（便于测试 monkeypatch）。"""
    _HANDLERS[name] = fn
    logger.debug("registered MCP handler: %s", name)


def unregister_handler(name: str) -> None:
    _HANDLERS.pop(name, None)


def list_registered_handlers() -> list[str]:
    return sorted(_HANDLERS.keys())


# ---------------------------------------------------------------------------
# McpProxyServer
# ---------------------------------------------------------------------------


class McpProxyServer:
    """unix socket server，接收 MCP server 子进程的 tools/call 转发。

    Usage:
        proxy = McpProxyServer(ctx=HandlerCtx(...))
        await proxy.start()  # 创建 socket 文件 + listen
        # ... spawn MCP server 子进程，env HARNESS_MCP_SOCKET_PATH=proxy.socket_path
        # ... spawn claude，mcp-config 指向 MCP server 子进程命令
        try:
            await proxy.serve_until_stopped()
        finally:
            await proxy.stop()

    或更常见：把 ``serve_until_stopped`` 作为 task 跑，主任务在 claude run
    期间 await 它，结束时 cancel。
    """

    def __init__(self, ctx: HandlerCtx, *, socket_path: str | None = None):
        self.ctx = ctx
        # socket_path: None = 自动生成临时路径；测试可指定
        self._socket_path = socket_path
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.Task] = set()
        self._next_request_id = 0  # 仅用于内部 trace；request_id 由 MCP server 生成

    @property
    def socket_path(self) -> str | None:
        return self._socket_path

    async def start(self) -> str:
        """启动 unix socket server，返回 socket path。

        创建 socket 文件路径（如果未指定），bind + listen。
        """
        if self._server is not None:
            raise RuntimeError("McpProxyServer already started")

        if self._socket_path is None:
            # 临时文件目录 + 唯一文件名（不能用 NamedTemporaryFile — 它会预创建文件）
            tmp_dir = tempfile.gettempdir()
            unique = f"harness-mcp-{os.getpid()}-{id(self)}.sock"
            self._socket_path = str(Path(tmp_dir) / unique)

        # 如果 socket 文件已存在（之前 crash 残留），删掉
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        logger.info("McpProxyServer listening on %s", self._socket_path)
        return self._socket_path

    async def stop(self) -> None:
        """关闭 server 并清理 socket 文件。"""
        if self._server is None:
            return

        # cancel 所有正在跑的 connection handler
        for task in list(self._connections):
            task.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
        self._connections.clear()

        self._server.close()
        await self._server.wait_closed()
        self._server = None

        if self._socket_path and os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError as e:
                logger.warning("failed to clean socket %s: %s", self._socket_path, e)
        logger.info("McpProxyServer stopped")

    async def serve_until_stopped(self) -> None:
        """阻塞直到 stop() 被调用。供主任务 await 或 create_task 后台跑。"""
        if self._server is None:
            raise RuntimeError("call start() first")
        # asyncio.Server.serve_forever 在 Py3.7+ 可用
        await self._server.serve_forever()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """每个 MCP server 子进程连接对应一个 task。"""
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug("proxy: client connected from %s", peer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # client disconnected
                try:
                    req = McpCallRequest.from_json_line(line.decode("utf-8"))
                except Exception as e:
                    logger.warning("proxy: malformed request line: %r err=%s", line[:200], e)
                    continue
                logger.debug("proxy: dispatching request_id=%d tool=%s", req.request_id, req.tool_name)

                resp = await self._dispatch(req)

                try:
                    writer.write((resp.to_json_line() + "\n").encode("utf-8"))
                    await writer.drain()
                except (ConnectionError, BrokenPipeError) as e:
                    logger.warning("proxy: failed to write response: %s", e)
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("proxy: client handler crashed")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug("proxy: client disconnected")

    async def _dispatch(self, req: McpCallRequest) -> McpCallResponse:
        """根据 tool_name 调 handler；handler 不存在或抛错时返回 is_error=True。"""
        handler = _HANDLERS.get(req.tool_name)
        if handler is None:
            logger.warning("proxy: no handler for tool %r (registered: %s)",
                           req.tool_name, list_registered_handlers())
            return McpCallResponse.text(
                req.request_id,
                f"unknown MCP tool: {req.tool_name}",
                is_error=True,
            )
        try:
            return await handler(req.arguments, self.ctx, req.request_id)
        except Exception as e:
            logger.exception("proxy: handler %s raised", req.tool_name)
            return McpCallResponse.text(
                req.request_id,
                f"handler error in {req.tool_name}: {type(e).__name__}: {e}",
                is_error=True,
            )


# ---------------------------------------------------------------------------
# 内置 handler: ping (Phase D.1 smoke test 用；D.5 起加 ask_user 等)
# ---------------------------------------------------------------------------


async def _ping_handler(
    arguments: dict[str, Any], ctx: HandlerCtx, request_id: int
) -> McpCallResponse:
    """Echo back the input — 用来验证 IPC 链路通。

    注册名: "ping"。ClaudeCodeExecutor mcp-config 暴露这个工具时用 mcp__harness__ping。
    """
    text = arguments.get("text", "")
    return McpCallResponse.text(request_id, f"pong: {text}")


def register_default_handlers() -> None:
    """注册内置 handler。

    加新工具 = 写 handlers/<tool>.py + 在本函数调 register()。
    """
    register_handler("ping", _ping_handler)
    # ask_user handler（Phase D.5 加入；桥接到现有 _human_io + chat.question 链路）
    from harness.mcp.handlers.ask_user import register as register_ask_user
    register_ask_user()
