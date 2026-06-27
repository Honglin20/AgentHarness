"""MCP handler 子包 — 每个 MCP 工具一个 handler 模块。

加新工具:
  1. 写 handlers/<tool>.py，实现 async handler(args, ctx, request_id) -> McpCallResponse
  2. 在 harness/mcp/server.py TOOLS 加工具定义（claude 通过 tools/list 看到它）
  3. 在 harness/mcp/proxy.py register_default_handlers() 注册 handler
  4. 加测试（in-process + e2e）

工具定义（inputSchema）必须与 handler 参数名一致，否则 claude 会传错参数。
"""
from harness.mcp.handlers.ask_user import (
    TOOL_DEFINITION as ASK_USER_TOOL_DEFINITION,
    register as register_ask_user,
)

__all__ = ["ASK_USER_TOOL_DEFINITION", "register_ask_user"]
