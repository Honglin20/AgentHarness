"""stream-json → harness event 翻译层（Phase B）。

设计目标（detailed-design.md §5）：
  - 纯函数：input = 单行 stream-json dict，output = list[TranslatedEvent]
  - 不接 event_bus、不 spawn 子进程
  - 完全可离线单元测试，fixture 来自真实 claude -p 录制

事件映射规则基于 Claude Code CLI 2.1.150 实测样本
（见 ``_fixtures/sample_with_bash.jsonl``）：

  | stream-json                              | → harness event        |
  |------------------------------------------|------------------------|
  | system/init                              | node.started           |
  | stream_event/content_block_delta(text)   | agent.text_delta       |
  | stream_event/content_block_delta(thinking)| agent.thinking_delta  |
  | assistant[tool_use]                      | agent.tool_call        |
  | user[tool_result]                        | agent.tool_result      |
  | result/success                           | node.completed         |
  | result/error                             | (no emit — executor owns; see P2-T3)|
  | system/api_retry                         | agent.api_retry        |
  | system/status (requesting/thinking)      | agent.status_update    |
  | 其他                                       | (ignored)              |

未知事件**不抛**——返回空列表 + debug log，保证翻译器对未来 claude 版本
schema 演化有韧性（对应 detailed-design.md §11 G6 风险）。

P2-T4 emit-uniqueness contract: ``result.is_error=true`` is NO LONGER
translated to ``node.failed``. The executor catches it via
``_extract_pre_translate`` and emits ``agent.executor_error`` (critical)
with the full context. Translator emitting ``node.failed`` here would
double-count failures on the frontend (ADR Decision 2 invariant).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共数据结构
# ---------------------------------------------------------------------------


@dataclass
class TranslateContext:
    """每次翻译调用都需要的事件路由元数据。

    所有由本翻译器产生的 harness event payload 都会带上 ``node_id`` /
    ``agent_name``，方便前端按节点过滤；``iteration`` / ``attempt`` 仅在
    node.started / node.completed / node.failed 等生命周期事件里出现。
    """

    node_id: str
    agent_name: str
    iteration: int = 1
    attempt: int = 1
    model: str | None = None
    tools: list[dict] | None = None  # ToolBrief list: [{name, description}]


@dataclass
class TranslatedEvent:
    """翻译产物。type 是 harness event type，payload 是对应 schema 的 dict。"""

    type: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# 翻译主入口
# ---------------------------------------------------------------------------


def translate(stream_event: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """把一行 stream-json 翻译成 0..N 个 harness event。

    未知/不支持的事件类型返回空列表（防御性解析，不抛）。

    Args:
        stream_event: 从 claude stdout 解析出的单行 JSON dict
        ctx: 路由元数据（node_id / agent_name / iteration / ...）

    Returns:
        0..N 个 TranslatedEvent；调用方负责把它们 emit 到 event_bus
    """
    if not isinstance(stream_event, dict):
        logger.debug("translate: non-dict stream_event ignored: %r", stream_event)
        return []

    kind = stream_event.get("type")
    handler = _DISPATCH.get(kind, _translate_unknown)
    return handler(stream_event, ctx)


# ---------------------------------------------------------------------------
# 各事件类型翻译函数
# ---------------------------------------------------------------------------


def _translate_system(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    subtype = ev.get("subtype")
    if subtype == "init":
        # node.started — 复用 system/init 触发；attempt/iteration 来自 ctx
        # tools 列表如果 system/init 提供了，可以转成 ToolBrief 格式
        raw_tools = ev.get("tools") or []
        tool_briefs: list[dict] = []
        for t in raw_tools:
            if isinstance(t, str):
                tool_briefs.append({"name": t, "description": ""})
            elif isinstance(t, dict):
                tool_briefs.append({
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                })
        payload: dict[str, Any] = {
            "node_id": ctx.node_id,
            "agent_name": ctx.agent_name,
            "attempt": ctx.attempt,
            "iteration": ctx.iteration,
        }
        if tool_briefs:
            payload["tools"] = tool_briefs
        if ctx.model:
            payload["model"] = ctx.model
        return [TranslatedEvent(type="node.started", payload=payload)]
    if subtype == "api_retry":
        return _translate_system_api_retry(ev, ctx)
    if subtype == "status":
        return _translate_system_status(ev, ctx)
    # system/hook_started / hook_response → 忽略（hook 事件不映射到 harness）
    return []


def _translate_system_api_retry(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """Translate system/api_retry → agent.api_retry.

    Claude Code emits this when an upstream API call is being retried
    (rate limit / transient 5xx). Surfacing it lets the frontend show
    real-time retry progress instead of a "stuck" feeling while the model
    is silently retrying under the hood.
    """
    payload: dict[str, Any] = {
        "node_id": ctx.node_id,
        "agent_name": ctx.agent_name,
    }
    # Claude stream-json fields (best-effort — names may evolve):
    #   retry_count: 1-indexed attempt number after the first try
    #   max_retries: configured retry budget
    #   wait_seconds: scheduled backoff
    for src, dst in (
        ("retry_count", "retry_count"),
        ("max_retries", "max_retries"),
        ("wait_seconds", "wait_seconds"),
        ("error", "error_message"),
    ):
        if ev.get(src) is not None:
            payload[dst] = ev.get(src)
    return [TranslatedEvent(type="agent.api_retry", payload=payload)]


def _translate_system_status(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """Translate system/status → agent.status_update.

    Claude Code emits "requesting" / "thinking" / etc. to signal liveness
    between message deltas. Frontend can show a spinner / progress hint
    so users do not assume the agent died during long gaps.
    """
    status = ev.get("status") or "unknown"
    payload: dict[str, Any] = {
        "node_id": ctx.node_id,
        "agent_name": ctx.agent_name,
        "status": status,
    }
    # Optional helpful fields (best-effort — claude versions differ)
    for src in ("duration_ms", "duration", "message"):
        v = ev.get(src)
        if v is not None:
            payload[src] = v
    return [TranslatedEvent(type="agent.status_update", payload=payload)]


def _translate_stream_event(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """stream_event 是 claude SDK 包装层；真正的 event 在 ev['event']。"""
    inner = ev.get("event")
    if not isinstance(inner, dict):
        return []
    inner_type = inner.get("type", "")

    if inner_type == "content_block_delta":
        delta = inner.get("delta") or {}
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text", "")
            if not text:
                return []
            return [TranslatedEvent(
                type="agent.text_delta",
                payload={
                    "node_id": ctx.node_id,
                    "agent_name": ctx.agent_name,
                    "text": text,
                },
            )]
        if delta_type == "thinking_delta":
            text = delta.get("thinking", "")
            if not text:
                return []
            return [TranslatedEvent(
                type="agent.thinking_delta",
                payload={
                    "node_id": ctx.node_id,
                    "agent_name": ctx.agent_name,
                    "text": text,
                },
            )]
        # input_json_delta / signature_delta 等 partial → 不翻译（最终 tool_use
        # 事件里有完整 input，partial 翻译会导致前端 tool_args 抖动）
        return []

    # message_start / message_delta / message_stop / content_block_start /
    # content_block_stop：用于跟踪状态但不直接 emit
    return []


def _translate_assistant(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """assistant 完整消息：只翻译 tool_use；text/thinking 已经在 stream_event
    delta 里翻译过，重复翻译会导致前端重复渲染。"""
    message = ev.get("message") or {}
    content = message.get("content") or []
    if not isinstance(content, list):
        return []

    out: list[TranslatedEvent] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            tool_name = block.get("name", "")
            tool_input = block.get("input") or {}
            tool_call_id = block.get("id", "")
            if not tool_call_id:
                logger.warning(
                    "translate: tool_use without id; agent=%s name=%s — "
                    "tool_result matching will fail",
                    ctx.agent_name, tool_name,
                )
            out.append(TranslatedEvent(
                type="agent.tool_call",
                payload={
                    "node_id": ctx.node_id,
                    "agent_name": ctx.agent_name,
                    "tool_name": tool_name,
                    "tool_args": tool_input if isinstance(tool_input, dict) else {"value": tool_input},
                    "tool_call_id": tool_call_id,
                },
            ))
        # text / thinking block 在 stream_event delta 已翻译，不重复
    return out


def _translate_user(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """user 消息：只翻译 tool_result；其他 user 输入（如 resume feedback）
    在 claude-code 路径里由 harness 主动注入，不需要 emit。"""
    message = ev.get("message") or {}
    content = message.get("content") or []
    if not isinstance(content, list):
        return []

    out: list[TranslatedEvent] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        tool_call_id = block.get("tool_use_id", "")
        raw_content = block.get("content")
        # claude-code tool_result.content 可能是 str 或 list[{type:text,text:...}]
        if isinstance(raw_content, list):
            parts = []
            for c in raw_content:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
                else:
                    parts.append(str(c))
            result_text = "".join(parts)
        elif isinstance(raw_content, str):
            result_text = raw_content
        else:
            result_text = "" if raw_content is None else str(raw_content)

        out.append(TranslatedEvent(
            type="agent.tool_result",
            payload={
                "node_id": ctx.node_id,
                "agent_name": ctx.agent_name,
                # claude-code tool_result 不直接带 tool_name；用 tool_call_id 关联
                # 前端 AgentToolCallPayload 已记录了 tool_name，前端按 id 匹配
                "tool_name": "",  # 留空，前端按 tool_call_id 匹配 tool_call
                "result": result_text,
                "tool_call_id": tool_call_id,
            },
        ))
    return out


def _translate_result(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    """result 是 claude run 的最终事件，包含 duration/usage/cost/result。

    P2-T4: ``is_error=true`` is NO LONGER translated to ``node.failed``.
    The executor catches it via ``_extract_pre_translate`` and emits
    ``agent.executor_error`` (critical) with full context — translator
    emitting ``node.failed`` here would double-count failures on the
    frontend (ADR Decision 2 emit-uniqueness invariant).
    """
    is_error = bool(ev.get("is_error"))
    if is_error:
        # Executor owns this emit — return empty so callers do not double-emit.
        logger.debug(
            "translate: result.is_error=true; skipping (executor emits "
            "agent.executor_error instead, agent=%s", ctx.agent_name,
        )
        return []

    duration_ms = int(ev.get("duration_ms") or 0)
    usage = ev.get("usage") or {}
    cost = ev.get("total_cost_usd")

    token_usage = _build_token_usage(usage)

    payload: dict[str, Any] = {
        "node_id": ctx.node_id,
        "agent_name": ctx.agent_name,
        "duration_ms": duration_ms,
        "status": "success",
    }
    if token_usage is not None:
        payload["token_usage"] = token_usage
    if cost is not None:
        payload["cost_usd"] = float(cost)

    final_result = ev.get("result")
    if isinstance(final_result, str):
        # 末消息文本；Phase E 会做 JSON 提取，这里把原文挂到 output_result
        # 让前端在 schema 校验前能看到 raw 输出
        payload["output_result"] = {"raw": final_result}

    return [TranslatedEvent(type="node.completed", payload=payload)]


def _translate_unknown(ev: dict, ctx: TranslateContext) -> list[TranslatedEvent]:
    logger.debug(
        "translate: unknown stream-json type=%r; ignored (defensive parsing)",
        ev.get("type"),
    )
    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_token_usage(usage: dict) -> dict | None:
    """把 claude usage 转成 harness NodeCompletedPayload.token_usage schema。

    harness schema (frontend/src/types/events.ts TokenUsage):
      { input, output, total, cache_hit?, reasoning? }

    claude usage 提供: input_tokens / output_tokens / cache_read_input_tokens /
    cache_creation_input_tokens / reasoning_tokens 等。
    """
    if not usage:
        return None
    try:
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        cache_hit = usage.get("cache_read_input_tokens")
        reasoning = usage.get("reasoning_tokens")
        result: dict[str, Any] = {
            "input": inp,
            "output": out,
            "total": inp + out,
        }
        if cache_hit is not None:
            result["cache_hit"] = int(cache_hit)
        if reasoning is not None:
            result["reasoning"] = int(reasoning)
        return result
    except (TypeError, ValueError) as e:
        logger.debug("translate: failed to build token_usage from %r: %s", usage, e)
        return None


# ---------------------------------------------------------------------------
# 分派表
# ---------------------------------------------------------------------------

_DISPATCH: dict = {
    "system": _translate_system,
    "stream_event": _translate_stream_event,
    "assistant": _translate_assistant,
    "user": _translate_user,
    "result": _translate_result,
}
