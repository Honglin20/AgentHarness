"""harness MCP server 子包 — Phase D 实现。

包结构:
  - ``protocol``: IPC 消息定义（主进程 ↔ MCP server 子进程之间的 unix socket
    消息格式）
  - ``proxy``: 主进程内的 unix socket server，接收子进程转发的 tools/call
    分派到 handler（ask_user / TodoTool / render_chart / ...）
  - ``server``: claude 子进程的 stdio JSON-RPC server，把 tools/call 通过
    unix socket 转发到主进程
  - ``handlers/``: 每个 MCP 工具一个 handler 模块；handler 在主进程内运行

为什么用 unix socket 而不是直接共享内存:
  - claude --mcp-config 自己 spawn MCP server 子进程，主进程不能注入 fd；
    只能通过文件系统路径（unix socket path）让子进程找到主进程
  - unix socket 比 TCP 更安全（无端口暴露），比文件轮询更实时
"""
from harness.mcp.protocol import (
    McpCallRequest,
    McpCallResponse,
    McpError,
    PROTOCOL_VERSION,
)

__all__ = [
    "McpCallRequest",
    "McpCallResponse",
    "McpError",
    "PROTOCOL_VERSION",
]
