"""IPC 消息格式 — 主进程 McpProxy ↔ MCP server 子进程之间的 unix socket 协议。

为什么不用 JSON-RPC 双向:
  JSON-RPC 是 claude ↔ MCP server 之间的协议（带 id 对齐）；
  MCP server ↔ 主进程之间是简化的 request/response（一个 tools/call 对应一个
  McpCallResponse），不需要 JSON-RPC 的批量/通知语义，所以用 line-delimited
  JSON + 自己的 request_id 关联就够，更轻。

消息流（一次 tools/call ask_user）:
  1. claude -- stdout -- MCP server: {"jsonrpc":"2.0","method":"tools/call",...}
  2. MCP server 抽出 name + arguments，封装为 McpCallRequest，写 socket
  3. 主进程 proxy 读 socket，dispatch 到 ask_user handler
  4. handler emit chat.question + await _human_io.wait(future)
  5. WS 收 chat.answer → resolve_answer → future.set_result
  6. handler 拿到 answer，构造 McpCallResponse 写回 socket
  7. MCP server 把 response 转成 JSON-RPC tools/call result 发回 claude
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# MCP 协议版本（claude ↔ MCP server 之间握手时上报，与 IPC 协议无关）
PROTOCOL_VERSION = "2024-11-05"


@dataclass
class McpCallRequest:
    """MCP server → 主进程: 转发 claude 的 tools/call。

    主进程 proxy 收到后按 ``tool_name`` dispatch 到对应 handler。
    """

    request_id: int  # MCP server 生成的请求 id，response 必须带同样的值
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps({
            "kind": "call_request",
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
        })

    @classmethod
    def from_json_line(cls, line: str) -> "McpCallRequest":
        d = json.loads(line)
        assert d.get("kind") == "call_request", f"expected call_request, got {d.get('kind')!r}"
        return cls(
            request_id=int(d["request_id"]),
            tool_name=d["tool_name"],
            arguments=d.get("arguments") or {},
        )


@dataclass
class McpCallResponse:
    """主进程 → MCP server: handler 执行结果。

    content 是 MCP CallToolResult.content 的 list 形式（一般 [{"type":"text","text":...}]），
    MCP server 直接塞进 JSON-RPC result 里。
    """

    request_id: int
    content: list[dict[str, Any]]  # MCP content blocks
    is_error: bool = False

    def to_json_line(self) -> str:
        return json.dumps({
            "kind": "call_response",
            "request_id": self.request_id,
            "content": self.content,
            "is_error": self.is_error,
        })

    @classmethod
    def from_json_line(cls, line: str) -> "McpCallResponse":
        d = json.loads(line)
        assert d.get("kind") == "call_response", f"expected call_response, got {d.get('kind')!r}"
        return cls(
            request_id=int(d["request_id"]),
            content=d.get("content") or [],
            is_error=bool(d.get("is_error", False)),
        )

    @classmethod
    def text(cls, request_id: int, text: str, *, is_error: bool = False) -> "McpCallResponse":
        """快捷构造：单一 text content block。"""
        return cls(
            request_id=request_id,
            content=[{"type": "text", "text": text}],
            is_error=is_error,
        )


@dataclass
class McpError:
    """IPC 错误响应 — handler 抛异常或 socket 协议错时用。

    目前用 ``McpCallResponse(is_error=True)`` 表达 handler 失败；
    本类保留给协议级错误（malformed request_id / unknown kind 等），
    当前 Phase D 实现仅用 McpCallResponse。
    """

    request_id: int
    code: int
    message: str

    def to_json_line(self) -> str:
        return json.dumps({
            "kind": "error",
            "request_id": self.request_id,
            "code": self.code,
            "message": self.message,
        })
