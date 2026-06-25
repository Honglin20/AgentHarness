"""Phase D.1 — McpProxyServer 单元测试 + handler registry。

测试用 pytest-asyncio (mode=auto)；所有需要 event loop 的测试都是 async def。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from harness.mcp.proxy import (
    HandlerCtx,
    McpProxyServer,
    _HANDLERS,
    list_registered_handlers,
    register_default_handlers,
    register_handler,
    unregister_handler,
)
from harness.mcp.protocol import McpCallRequest, McpCallResponse


@pytest.fixture
def clean_handlers():
    """每个测试前后清空 _HANDLERS，避免相互污染。"""
    saved = dict(_HANDLERS)
    _HANDLERS.clear()
    yield
    _HANDLERS.clear()
    _HANDLERS.update(saved)


@pytest.fixture
def ctx() -> HandlerCtx:
    return HandlerCtx(workflow_id="wf-1", node_id="node-1", agent_name="agent-1")


# ---------------------------------------------------------------------------
# Handler registry — 同步测试
# ---------------------------------------------------------------------------


class TestHandlerRegistry:
    def test_register_and_list(self, clean_handlers):
        async def handler(args, ctx, request_id):
            return McpCallResponse.text(request_id, "ok")

        register_handler("foo", handler)
        assert "foo" in list_registered_handlers()

    def test_unregister_removes(self, clean_handlers):
        async def handler(args, ctx, request_id):
            return McpCallResponse.text(request_id, "ok")

        register_handler("foo", handler)
        unregister_handler("foo")
        assert "foo" not in list_registered_handlers()

    def test_unregister_unknown_is_silent(self, clean_handlers):
        unregister_handler("nonexistent")  # no throw

    def test_register_default_handlers_includes_ping(self, clean_handlers):
        register_default_handlers()
        assert "ping" in list_registered_handlers()


# ---------------------------------------------------------------------------
# Ping handler — 同步测试，handler 是 async 但能直接 await
# ---------------------------------------------------------------------------


class TestPingHandler:
    @pytest.mark.asyncio
    async def test_ping_handler_echos_text(self, clean_handlers):
        register_default_handlers()
        handler = _HANDLERS["ping"]
        result = await handler({"text": "hello"}, HandlerCtx("wf", "n", "a"), 99)
        assert isinstance(result, McpCallResponse)
        assert result.request_id == 99  # request_id 透传
        assert result.content == [{"type": "text", "text": "pong: hello"}]
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_ping_handler_missing_text_arg(self, clean_handlers):
        register_default_handlers()
        handler = _HANDLERS["ping"]
        result = await handler({}, HandlerCtx("wf", "n", "a"), 1)
        assert result.content == [{"type": "text", "text": "pong: "}]


# ---------------------------------------------------------------------------
# McpProxyServer lifecycle — async tests
# ---------------------------------------------------------------------------


class TestProxyLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_socket_file(self, ctx, clean_handlers):
        register_default_handlers()
        proxy = McpProxyServer(ctx=ctx)
        try:
            socket_path = await proxy.start()
            assert os.path.exists(socket_path)
            assert proxy.socket_path == socket_path
        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_start_twice_raises(self, ctx):
        proxy = McpProxyServer(ctx=ctx)
        try:
            await proxy.start()
            with pytest.raises(RuntimeError, match=r"already started"):
                await proxy.start()
        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_stop_removes_socket_file(self, ctx):
        proxy = McpProxyServer(ctx=ctx)
        socket_path = await proxy.start()
        await proxy.stop()
        assert not os.path.exists(socket_path)

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(self, ctx):
        proxy = McpProxyServer(ctx=ctx)
        await proxy.stop()  # no throw

    @pytest.mark.asyncio
    async def test_start_with_explicit_socket_path(self, ctx, clean_handlers):
        """tmp_path 在 macOS 上路径太长（AF_UNIX 限制 108 字节）；
        用 tempfile.gettempdir 直接拼短路径。"""
        import tempfile
        register_default_handlers()
        custom = str(Path(tempfile.gettempdir()) / f"harness-test-{os.getpid()}-explicit.sock")
        proxy = McpProxyServer(ctx=ctx, socket_path=custom)
        try:
            result_path = await proxy.start()
            assert result_path == custom
            assert os.path.exists(custom)
        finally:
            await proxy.stop()
            if os.path.exists(custom):
                os.unlink(custom)


# ---------------------------------------------------------------------------
# Proxy + socket client (in-process, same loop)
# ---------------------------------------------------------------------------


class TestProxyDispatch:
    """同 loop 内启动 proxy + 用 asyncio.open_unix_connection 当 client。"""

    @pytest.fixture
    async def running_proxy(self, ctx, clean_handlers):
        """启动 proxy + serve task 在 background，yield socket_path。"""
        register_default_handlers()
        proxy = McpProxyServer(ctx=ctx)
        socket_path = await proxy.start()
        serve_task = asyncio.create_task(proxy.serve_until_stopped())
        try:
            yield socket_path
        finally:
            serve_task.cancel()
            try:
                await asyncio.gather(serve_task, return_exceptions=True)
            except Exception:
                pass
            await proxy.stop()

    async def _call_via_socket(self, socket_path: str, req: McpCallRequest) -> McpCallResponse:
        """连 socket 发请求，等响应。"""
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            writer.write((req.to_json_line() + "\n").encode("utf-8"))
            await writer.drain()
            line = await reader.readline()
            return McpCallResponse.from_json_line(line.decode("utf-8"))
        finally:
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_dispatch_ping_returns_pong(self, running_proxy):
        socket_path = running_proxy
        req = McpCallRequest(request_id=10, tool_name="ping", arguments={"text": "world"})
        resp = await self._call_via_socket(socket_path, req)
        assert resp.request_id == 10
        assert resp.content == [{"type": "text", "text": "pong: world"}]
        assert resp.is_error is False

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error(self, running_proxy):
        socket_path = running_proxy
        req = McpCallRequest(request_id=11, tool_name="bogus_tool", arguments={})
        resp = await self._call_via_socket(socket_path, req)
        assert resp.is_error is True
        assert "unknown MCP tool" in resp.content[0]["text"]

    @pytest.mark.asyncio
    async def test_dispatch_handler_raising_returns_error_response(
        self, running_proxy, clean_handlers
    ):
        """handler 抛异常 → proxy 返回 is_error=True，不挂连接。"""
        async def bad_handler(args, ctx, request_id):
            raise ValueError("boom")

        register_handler("ping", bad_handler)  # 覆盖默认 ping
        socket_path = running_proxy
        req = McpCallRequest(request_id=12, tool_name="ping", arguments={})
        resp = await self._call_via_socket(socket_path, req)
        assert resp.is_error is True
        assert "handler error" in resp.content[0]["text"]
        assert "boom" in resp.content[0]["text"]

    @pytest.mark.asyncio
    async def test_dispatch_malformed_request_line_does_not_crash(self, running_proxy):
        socket_path = running_proxy
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            # 写一行坏 JSON
            writer.write(b"not valid json\n")
            await writer.drain()
            # 紧接着写一行合法
            req = McpCallRequest(request_id=13, tool_name="ping", arguments={"text": "x"})
            writer.write((req.to_json_line() + "\n").encode("utf-8"))
            await writer.drain()
            line = await reader.readline()
            resp = McpCallResponse.from_json_line(line.decode("utf-8"))
        finally:
            writer.close()
            await writer.wait_closed()
        assert resp.request_id == 13
        assert resp.content == [{"type": "text", "text": "pong: x"}]

    @pytest.mark.asyncio
    async def test_dispatch_multiple_sequential_calls(self, running_proxy):
        """同一连接发多个请求，验证 server 不串味儿。"""
        socket_path = running_proxy
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            for i in range(5):
                req = McpCallRequest(
                    request_id=100 + i,
                    tool_name="ping",
                    arguments={"text": f"call-{i}"},
                )
                writer.write((req.to_json_line() + "\n").encode("utf-8"))
                await writer.drain()
                line = await reader.readline()
                resp = McpCallResponse.from_json_line(line.decode("utf-8"))
                assert resp.request_id == 100 + i
                assert resp.content == [{"type": "text", "text": f"pong: call-{i}"}]
        finally:
            writer.close()
            await writer.wait_closed()
