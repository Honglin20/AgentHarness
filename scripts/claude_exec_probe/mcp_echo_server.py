"""Minimal stdio MCP echo server — 手写 JSON-RPC 2.0，零依赖。

理由：fastmcp banner/启动延迟疑似导致 claude WaitForMcpServers 之后仍找不到工具；
V4 是死活命题，需要完全可控的协议层。

协议：每行一个 JSON-RPC 2.0 消息。响应同步发出。
- initialize -> InitializeResult (capabilities.tools)
- notifications/initialized -> notification, 无响应
- tools/list -> ListToolsResult (单个 echo 工具)
- tools/call -> CallToolResult (content[0].text = "echoed: <text>")

行为：echo(text, block_seconds) 阻塞 block_seconds 秒后返回，便于 V4 验证。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

LOG_PATH = Path(__file__).parent / "mcp_echo_server.log"
LOG_PATH.unlink(missing_ok=True)

logger = logging.getLogger("mcp_echo")
logger.setLevel(logging.INFO)
_fh = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.addHandler(_fh)

PROTOCOL_VERSION = "2024-11-05"

ECHO_TOOL_DEF = {
    "name": "echo",
    "description": "Echo back the given text. If block_seconds > 0, the tool will wait that many seconds before responding.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "block_seconds": {"type": "integer", "default": 0},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def make_response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_initialize(req_id: int, params: dict) -> dict:
    return make_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": "echo-server", "version": "0.1.0"},
        "capabilities": {"tools": {"listChanged": False}},
    })


def handle_tools_list(req_id: int) -> dict:
    return make_response(req_id, {"tools": [ECHO_TOOL_DEF]})


def handle_tools_call(req_id: int, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    if name != "echo":
        return make_error(req_id, -32602, f"unknown tool: {name}")

    text = args.get("text", "")
    block = int(args.get("block_seconds") or 0)

    t0 = time.time()
    logger.info(f"CALL echo text={text!r} block_seconds={block}")
    if block > 0:
        logger.info(f"  -> blocking {block}s (simulating long-running handler)")
        # 真阻塞；注意我们在 sync 循环里跑（mainloop 是 sync readline）
        time.sleep(block)
    elapsed = time.time() - t0
    result_text = f"echoed: {text}"
    logger.info(f"  -> returning after {elapsed:.2f}s: {result_text!r}")

    return make_response(req_id, {
        "content": [{"type": "text", "text": result_text}],
        "isError": False,
    })


def mainloop() -> None:
    logger.info("echo-server (handwritten JSON-RPC) ready on stdio")
    # 重要：stdin 行缓冲
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.info(f"BAD JSON: {e}: {raw[:200]!r}")
            continue

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}
        logger.info(f"<-- method={method} id={req_id}")

        if method == "initialize":
            send(handle_initialize(req_id, params))
        elif method == "notifications/initialized":
            # notification，无 id 无响应
            pass
        elif method == "tools/list":
            send(handle_tools_list(req_id))
        elif method == "tools/call":
            send(handle_tools_call(req_id, params))
        elif method in ("resources/list", "prompts/list"):
            # 客户端 probe 时回空
            send(make_response(req_id, {"resources": []} if method == "resources/list" else {"prompts": []}))
        elif req_id is not None:
            send(make_error(req_id, -32601, f"method not found: {method}"))
        # 纯 notification 未处理则忽略


if __name__ == "__main__":
    mainloop()
