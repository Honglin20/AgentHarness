"""ask_user MCP handler — claude-code 路径的 HITL 桥接。

镜像 harness/tools/ask_user.py 的 pydantic-ai 版 ask_user 逻辑：
  emit chat.question → _human_io.register → wait(future) → resolve → return

区别只在 wrap 层:
  - pydantic-ai 版: 接 RunContext，返回 str（pydantic-ai tool 协议）
  - MCP 版（本模块）: 接 (arguments, HandlerCtx, request_id)，返回 McpCallResponse
                     （claude 通过 MCP tools/call 调用）

emit / register / wait / resolve 链路与 pydantic-ai 版完全一致，所以 WS 接收
chat.answer → resolve_answer → _human_io.resolve 这条链路不需要改。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from harness.mcp.protocol import McpCallResponse
from harness.mcp.proxy import HandlerCtx, register_handler
from harness.tools._human_io import (
    register as register_future,
    wait as wait_future,
)
from harness.tools.ask_user import (
    AskUserOption,
    TIMEOUT_MESSAGE,
    _normalize_raw,
    _resolve_timeout,
    assemble_answer,
)

logger = logging.getLogger(__name__)

TOOL_NAME = "ask_user"

# 工具定义 — claude 通过 tools/list 看到的；inputSchema 与 handler 参数名一致
TOOL_DEFINITION: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Ask the user a question and wait for their response. "
        "SUPPORTS THREE MODES:\n"
        "1. Multiple-choice: set options=[{label, description?, value?}, ...] "
        "(multi_select=True for checkbox, default False for radio).\n"
        "2. Open-ended: omit options. User types free text. "
        "Use input_type='textarea' for long answers, 'number' for numeric.\n"
        "3. Choice + other: options + allow_custom_input=True (default).\n\n"
        "Returns the user's answer as a plain string. "
        "Blocks until answered (HARNESS_ASK_USER_TIMEOUT env, -1 = wait forever)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask. Be specific. Markdown supported.",
            },
            "options": {
                "type": "array",
                "description": (
                    "Choice list. Each item: {label (button text), "
                    "description? (tooltip), value? (return value, defaults to label)}. "
                    "2-6 items recommended. Omit for open-ended."
                ),
                "items": {"type": "object"},
            },
            "header": {
                "type": "string",
                "description": "Short label shown above the question (e.g. 'Model'). Max 12 chars.",
            },
            "multi_select": {
                "type": "boolean",
                "default": False,
                "description": "True = checkbox (pick several). False = radio (pick one).",
            },
            "allow_custom_input": {
                "type": "boolean",
                "default": True,
                "description": "True = show 'Other' text box alongside options.",
            },
            "input_type": {
                "type": "string",
                "enum": ["text", "number", "url", "textarea"],
                "default": "text",
                "description": "Keyboard hint for free-text input.",
            },
            "input_placeholder": {
                "type": "string",
                "description": "Placeholder text in the free-text input box.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}


async def ask_user_handler(
    arguments: dict[str, Any], ctx: HandlerCtx, request_id: int
) -> McpCallResponse:
    """MCP tools/call handler — 见模块 docstring 的链路图。"""
    question = arguments.get("question", "")
    options_raw = arguments.get("options") or []
    header = arguments.get("header")
    multi_select = bool(arguments.get("multi_select", False))
    allow_custom_input = bool(arguments.get("allow_custom_input", True))
    input_type = arguments.get("input_type", "text")
    input_placeholder = arguments.get("input_placeholder")

    # parse options（与 pydantic-ai 版一致）
    try:
        options = [AskUserOption(**o) for o in options_raw] if options_raw else None
    except Exception as e:
        logger.warning("ask_user: malformed options %r: %s", options_raw, e)
        return McpCallResponse.text(
            request_id,
            f"ask_user: invalid options: {e}",
            is_error=True,
        )

    question_id = str(uuid.uuid4())
    timeout = _resolve_timeout()

    # 1. emit chat.question — 前端 ConversationStore 会渲染 AgentQuestionCard
    if ctx.event_bus is not None:
        payload: dict[str, Any] = {
            "node_id": ctx.node_id,
            "agent_name": ctx.agent_name,
            "question_id": question_id,
            "question": question,
            "header": header,
            "options": [o.model_dump() for o in options] if options else None,
            "multi_select": multi_select,
            "allow_custom_input": allow_custom_input,
            "input_type": input_type,
            "input_placeholder": input_placeholder,
        }
        if ctx.workflow_id:
            payload["workflow_id"] = ctx.workflow_id
        ctx.event_bus.emit("chat.question", payload)

    # 2. register future + wait（与 pydantic-ai 版完全一致）
    future = await register_future(question_id)
    raw = await wait_future(future, timeout=timeout)

    # 3. timeout 处理
    if raw is None:
        logger.warning(
            "ask_user MCP timeout qid=%s timeout=%r agent=%s",
            question_id, timeout, ctx.agent_name,
        )
        if ctx.event_bus is not None:
            ctx.event_bus.emit("chat.timeout", {
                "workflow_id": ctx.workflow_id,
                "node_id": ctx.node_id,
                "agent_name": ctx.agent_name,
                "question_id": question_id,
                "timeout_sec": timeout,
            })
        return McpCallResponse.text(request_id, TIMEOUT_MESSAGE)

    # 4. assemble answer
    payload = _normalize_raw(raw)
    answer_str = assemble_answer(payload, options, multi_select, allow_custom_input)

    logger.info(
        "ask_user MCP return OK qid=%s agent=%s answer_str=%r",
        question_id, ctx.agent_name, answer_str,
    )

    # 5. emit chat.answer（让 WS replay 也能看到 resolved 状态）
    if ctx.event_bus is not None:
        ctx.event_bus.emit("chat.answer", {
            "workflow_id": ctx.workflow_id,
            "node_id": ctx.node_id,
            "agent_name": ctx.agent_name,
            "question_id": question_id,
            "answer": answer_str,
            "raw": payload,
        })

    return McpCallResponse.text(request_id, answer_str)


def register() -> None:
    """注册 ask_user handler 到 proxy 全局 _HANDLERS。"""
    register_handler(TOOL_NAME, ask_user_handler)
