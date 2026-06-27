"""LLMExecutor — encapsulates the Pydantic AI agent iteration loop.

Extracted from MacroGraphBuilder._make_node_func() so that the core LLM
call + streaming + interrupt-checking logic lives in one focused class.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic_graph import End
from pydantic_ai.messages import ModelRequest, SystemPromptPart, RetryPromptPart

from harness.extensions.base import ToolCtx
from harness.extensions.bus import safe_emit
from harness.engine.token_aggregator import TokenAggregator
from harness.engine.tool_resolution import ToolResolution

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """What LLMExecutor.run() returns."""

    agent_run: Any  # pydantic_ai AgentRun
    stop_regen: dict[str, Any] | None = None
    ttft_ms: int | None = None


@runtime_checkable
class BaseExecutor(Protocol):
    """协议：DAG 节点执行器接口。

    LLMExecutor (pydantic-ai 路径) 和 ClaudeCodeExecutor (claude-code 路径,
    Phase C 实现) 都实现此协议。node_factory 通过 ``make_executor`` 工厂
    按 ``agent_def.executor`` 字段分派到具体实现。

    新增 backend = 实现此协议 + 在 ``make_executor`` 注册分支 +
    在 ``harness.core.agent.VALID_EXECUTORS`` 加白名单。

    添加新方法到本协议前，必须确认 LLMExecutor 与 ClaudeCodeExecutor
    均能语义一致地实现，否则 DAG 引擎会出现 backend-coupled 行为。
    """

    #: 本节点执行过程中累计的工具调用记录；node_factory 用它生成 sidecar IO 快照
    #: 和 step 计数。每个 entry 至少含 tool_name / tool_call_id / input / output。
    tool_calls: list[dict[str, Any]]

    async def run(self, context: str) -> AgentRunResult:
        """执行一次 agent run。``context`` 是 build_node_prompt 拼出的 user message。

        返回 AgentRunResult；失败由调用方（execute_with_retry）分类重试。
        """
        ...

    def record_usage(self, usage_obj: Any) -> None:
        """把一次 LLM 请求的 usage（input/output/cache tokens）记进聚合器。

        node_factory 在 run 结束后调一次，用于 BudgetBar 和 sidecar 持久化。
        """
        ...

    def get_last_request_usage(self) -> dict[str, int]:
        """返回最近一次 LLM 请求的 usage delta（key: input/output/cache_read/cache_creation）。

        用于单次请求的 token 报告；与 record_usage 的累计语义不同。
        """
        ...

    def resolve_tools(self) -> list[ToolResolution]:
        """返回本 backend 对 agent 声明工具的解析结果。

        每个 executor 子类实现具体解析规则（claude-code 走 cli_bridge_tools
        config；pydantic-ai 全部当 in-process function；未来的 opencode 等
        backend 各自定义）。``node_factory`` 在 ``node.started`` emit 时调用
        本方法把结果传给前端展示。

        返回 ``list[ToolResolution]``，顺序与 ``agent_def.tools`` 一致；
        agent 没声明工具时返回 ``[]``。
        """
        ...


class LLMExecutor:
    """Run a Pydantic AI agent via iter() with streaming + interrupt support.

    Parameters
    ----------
    pydantic_agent
        The PydanticAI Agent instance (already created with tools, model, etc.).
    deps
        AgentDeps (or any deps_type) passed to the agent run.
    event_bus
        Optional Bus for emitting WS events (agent.text_delta, tool_call, etc.).
    workflow_id, node_id, agent_name
        Identifiers used in event payloads.
    ext_ctx
        Optional NodeCtx — if provided, on_llm_delta / on_tool_call hooks are
        invoked via bus.run_hooks().
    check_interrupt
        ``(workflow_id, agent_name) -> dict | None``.
        Called synchronously at multiple points during the iteration loop.
        Returns a non-None dict to signal a stop-and-regenerate request.
    cancel_fn
        ``sync (workflow_id) -> None``.  Called when an interrupt is detected
        (e.g. cancels running subprocess).
    """

    def __init__(
        self,
        pydantic_agent,
        deps,
        *,
        event_bus: Any | None = None,
        workflow_id: str = "",
        node_id: str = "",
        agent_name: str = "",
        ext_ctx: Any | None = None,
        check_interrupt: Callable[[str, str], dict[str, Any] | None] | None = None,
        cancel_fn: Callable[[str], None] | None = None,
        token_aggregator: TokenAggregator | None = None,
        request_limit: int | None = None,
        tools_declared: list[str] | None = None,
    ):
        self._agent = pydantic_agent
        self._deps = deps
        self._bus = event_bus
        self._wid = workflow_id
        self._node_id = node_id
        self._agent_name = agent_name
        self._ext_ctx = ext_ctx
        self._check_interrupt = check_interrupt
        self._cancel_fn = cancel_fn
        self._token_aggregator = token_aggregator
        # Per-agent LLM request budget. None → resolve from HARNESS_REQUEST_LIMIT
        # env (default 200). Forwarded to agent.iter(usage_limits=...) — controls
        # when PydanticAI raises UsageLimitExceeded (see llm_retry.py classify).
        self._request_limit = request_limit
        # Declared tool names (workflow.json ``tools`` field). Used by
        # resolve_tools() to surface what the operator wrote vs what the
        # pydantic-ai Agent actually registered. None when the executor
        # was built outside the standard node_factory path (tests / direct
        # ad-hoc construction) — resolve_tools() returns [] in that case.
        self._tools_declared: list[str] | None = tools_declared
        self.tool_calls: list[dict[str, Any]] = []
        self._span_seq = 0
        self._last_ttft_ms: int | None = None
        # Per-instance throttle counter for text_delta backpressure.
        # Class-level would be shared across concurrent workflows, breaking
        # per-workflow throttle semantics.
        self._delta_skip_counter: int = 0
        # Baselines for per-request usage delta. Pydantic AI's ctx.state.usage
        # accumulates within iter(), so subtracting baseline (captured at model
        # request entry) from current gives the single-shot request usage.
        # Reset in run() entry so retries (which replay iter() with fresh usage)
        # don't leak the previous attempt's baseline.
        self._baseline_input: int = 0
        self._baseline_output: int = 0
        self._baseline_cache_hit: int = 0
        self._last_input: int = 0
        self._last_output: int = 0
        self._last_cache_hit: int = 0

    def resolve_tools(self) -> list[ToolResolution]:
        """pydantic-ai backend resolution. See ``resolve_tools_for_backend``."""
        from harness.engine.tool_resolution import resolve_tools_for_backend

        if not self._tools_declared:
            return []
        return resolve_tools_for_backend(self._tools_declared, "pydantic-ai")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _next_span_id(self) -> str:
        self._span_seq += 1
        return f"{self._node_id}-s{self._span_seq}"

    def _build_schema_retry_reminder(self, message_history: list) -> str | None:
        """If the previous model request ended with a RetryPromptPart, build
        a schema-recovery reminder telling the model exactly what to emit.

        Returns None when:
          - the last message is not a RetryPromptPart (no retry in flight)
          - the agent has no ``output_type`` BaseModel (free-text output)
          - schema introspection fails (defensive — never blocks the run)

        The reminder content is identical in spirit to the system prompt
        already injected at node_factory, but it is re-emphasised here
        because RetryPromptPart is the *immediate* feedback the model is
        responding to. Naming the tool (``final_result``) and re-showing
        the schema gives the model the clearest path back to a valid call.
        """
        if not message_history:
            return None
        last = message_history[-1]
        # RetryPromptPart lives inside a ModelRequest's parts list.
        has_retry = False
        if isinstance(last, ModelRequest):
            has_retry = any(isinstance(p, RetryPromptPart) for p in last.parts)
        if not has_retry:
            return None

        # Introspect the agent's output_type. For free-text agents (no
        # BaseModel) there's no schema to remind about.
        import json as _json
        try:
            from harness.engine.schema_utils import strip_schema
            from harness.prompts import feedback
            schema_obj = getattr(self._agent, "_output_schema", None)
            toolset = getattr(self._agent, "_output_toolset", None)
            if toolset is None or not getattr(toolset, "_tool_defs", None):
                return None
            td = toolset._tool_defs[0]
            schema = strip_schema(td.parameters_json_schema)
            return feedback.schema_retry_msg(
                td.name, _json.dumps(schema, indent=2, ensure_ascii=False)
            )
        except Exception:
            logger.debug(
                "schema-retry reminder build failed for %s; relying on default pydantic-ai feedback",
                self._agent_name, exc_info=True,
            )
            return None

    async def run(self, context: str) -> AgentRunResult:
        """Execute the agent and return the result.

        Handles:
        - iter() loop with streaming text deltas
        - tool_call / tool_result event emission
        - interrupt (stop-and-regenerate) detection at every iteration step
        """
        # Bind the workflow_id into the async context so chart/render_chart
        # (called by the agent as a Pydantic AI tool, deep in the call stack)
        # can stamp it on its events. Without this, server's chart fallback
        # used to guess the workflow by node_id and could route across
        # concurrently-running workflows.
        from harness.tools._truncate import truncation_context
        from harness.tools.chart import (
            reset_chart_workflow_context,
            set_chart_workflow_context,
        )
        wid_token = set_chart_workflow_context(self._wid or None)

        # Reset per-request usage tracking. execute_with_retry replays
        # run_fn on retry, and Pydantic AI starts each iter() with a fresh
        # usage accumulator — we must mirror that here so _last_* reflects
        # only the current attempt's most recent model request.
        self._baseline_input = 0
        self._baseline_output = 0
        self._baseline_cache_hit = 0
        self._last_input = 0
        self._last_output = 0
        self._last_cache_hit = 0

        # Publish (bus, wid, node, agent) for tool-result truncation events.
        # ToolFactory._wrap_fn reads this via contextvars so it can emit
        # agent.tool_output_truncated without holding a back-reference.
        trunc_ctx = truncation_context(
            self._bus, self._wid, self._node_id, self._agent_name,
        )

        stop_regen: dict[str, Any] | None = None

        # Resolve per-agent request_limit: explicit > env (default 200). Wrapped
        # in UsageLimits and passed to agent.iter(). PydanticAI raises
        # UsageLimitExceeded mid-stream when exceeded — caught and re-classified
        # by llm_retry.execute_with_retry (category="usage_exceeded", no retry).
        from pydantic_ai.usage import UsageLimits
        effective_request_limit = (
            self._request_limit
            if self._request_limit is not None
            else int(os.environ.get("HARNESS_REQUEST_LIMIT", "200"))
        )
        usage_limits = UsageLimits(request_limit=effective_request_limit)

        try:
            with trunc_ctx:
                async with self._agent.iter(
                    context, deps=self._deps, usage_limits=usage_limits,
                ) as agent_run:
                    node = agent_run.next_node

                    while not isinstance(node, End):
                        if self._agent.is_model_request_node(node):
                            stop_regen = await self._handle_model_request(node, agent_run.ctx)
                            if stop_regen:
                                break
                            node = await agent_run.next(node)

                        elif self._agent.is_call_tools_node(node):
                            stop_regen = await self._handle_call_tools(node, agent_run.ctx)
                            if stop_regen:
                                break
                            node = await agent_run.next(node)

                        else:
                            node = await agent_run.next(node)

                return AgentRunResult(agent_run=agent_run, stop_regen=stop_regen, ttft_ms=self._last_ttft_ms)
        finally:
            reset_chart_workflow_context(wid_token)

    # ------------------------------------------------------------------
    # Token usage recording
    # ------------------------------------------------------------------

    def record_usage(self, usage_obj: Any) -> None:
        """Record token usage from a Pydantic AI usage object into the aggregator.

        Safe to call with None — does nothing if aggregator is unset or usage is missing.
        """
        if self._token_aggregator is None or usage_obj is None:
            return
        self._token_aggregator.record(
            self._agent_name,
            input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
            cache_hit_tokens=getattr(usage_obj, "prompt_cache_hit_tokens", 0) or 0,
            reasoning_tokens=getattr(usage_obj, "reasoning_tokens", 0) or 0,
        )

    # ------------------------------------------------------------------
    # Internal: model-request node (text streaming)
    # ------------------------------------------------------------------

    async def _handle_model_request(self, node, ctx) -> dict[str, Any] | None:
        """Stream model response text and thinking, emit deltas, check interrupts."""

        # Capture baseline usage BEFORE Pydantic AI increments it for this
        # request. ctx.state.usage accumulates across model requests within
        # an iter() run, so (current - baseline) at end-of-request = single-
        # shot usage for this request only.
        self._baseline_input = getattr(ctx.state.usage, "input_tokens", 0) or 0
        self._baseline_output = getattr(ctx.state.usage, "output_tokens", 0) or 0
        self._baseline_cache_hit = getattr(ctx.state.usage, "cache_read_tokens", 0) or 0

        # Inject reminder as a system message into message_history before the
        # Reminder-tracker injection used to live here (TodoReminderTracker).
        # Removed in TASK 4: the dynamic runtime_status system prompt
        # (registered in micro_agent.create) now surfaces todo progress every
        # turn via pydantic-ai's dynamic_ref mechanism — replacing the
        # counter-based, accumulating reminder nudges.

        # Schema-retry reminder: when the previous request ended with a
        # RetryPromptPart (pydantic-ai's signal that the model's output
        # failed schema validation — typically "Invalid JSON" because the
        # model emitted text instead of a ``final_result`` tool call),
        # inject a fresh reminder naming the tool and showing the expected
        # schema. The default pydantic-ai RetryPromptPart only says
        # "Invalid JSON: expected value at line 1 column 1" — models that
        # have drifted into a markdown-summary mode often can't tell what
        # to switch to. See 2026--06-17 adapter_generator incident.
        schema_reminder = self._build_schema_retry_reminder(ctx.state.message_history)
        if schema_reminder:
            ctx.state.message_history.append(
                ModelRequest(parts=[SystemPromptPart(content=schema_reminder)])
            )

        span_id = self._next_span_id()
        model_name = ""
        if hasattr(self._agent, "model"):
            m = self._agent.model
            model_name = str(getattr(m, "model_name", m) if hasattr(m, "model_name") else m)

        if self._bus:
            safe_emit(self._bus, "span.start", {
                "workflow_id": self._wid,
                "node_id": self._node_id,
                "agent_name": self._agent_name,
                "span_id": span_id,
                "span_type": "llm",
                "model": model_name,
                "ts": int(time.time() * 1000),
            })

        stream_start = time.monotonic()
        ttft_ms = None
        first_token_received = False

        async with node.stream(ctx) as stream:
            prev_text = ""
            prev_thinking = ""
            async for response in stream.stream_response():
                # Extract text parts
                current_text = "".join(
                    p.content for p in response.parts
                    if getattr(p, "part_kind", None) == "text"
                )
                delta = current_text[len(prev_text):]
                prev_text = current_text

                if delta:
                    self._emit_text_delta(delta)
                    await self._fire_llm_delta_hook(delta)

                # Extract thinking parts (e.g. DeepSeek reasoning)
                current_thinking = "".join(
                    p.content for p in response.parts
                    if getattr(p, "part_kind", None) == "thinking"
                )
                thinking_delta = current_thinking[len(prev_thinking):]
                prev_thinking = current_thinking

                if thinking_delta:
                    self._emit_thinking_delta(thinking_delta)

                # TTFT: measure time to first token
                if not first_token_received and (delta or thinking_delta):
                    ttft_ms = int((time.monotonic() - stream_start) * 1000)
                    first_token_received = True

                interrupt = self._poll_interrupt()
                if interrupt is not None:
                    return interrupt

        self._last_ttft_ms = ttft_ms

        # Compute single-shot usage for THIS model request by subtracting
        # the baseline captured at entry. Pydantic AI increments ctx.state.usage
        # inside node.stream() once the response finalizes, so by the time we
        # reach here current - baseline = this request's contribution.
        current_input = getattr(ctx.state.usage, "input_tokens", 0) or 0
        current_output = getattr(ctx.state.usage, "output_tokens", 0) or 0
        current_cache_hit = getattr(ctx.state.usage, "cache_read_tokens", 0) or 0

        last_input = current_input - self._baseline_input
        last_output = current_output - self._baseline_output
        last_cache_hit = current_cache_hit - self._baseline_cache_hit

        if last_input < 0 or last_output < 0:
            # Baseline was captured after Pydantic AI already incr'd —
            # indicates _handle_model_request was entered mid-increment or
            # the baseline capture point moved. Fail loud (log + ext.error)
            # and clamp to 0 so the workflow doesn't crash, but the operator
            # sees the instrumentation bug.
            logger.error(
                "agent.usage_update delta negative for %s: "
                "baseline=(in=%d,out=%d,cache=%d) current=(in=%d,out=%d,cache=%d) "
                "delta=(in=%d,out=%d,cache=%d) — baseline capture point is wrong",
                self._agent_name,
                self._baseline_input, self._baseline_output, self._baseline_cache_hit,
                current_input, current_output, current_cache_hit,
                last_input, last_output, last_cache_hit,
            )
            safe_emit(self._bus, "ext.error", {
                "extension": "llm_executor",
                "phase": "usage_delta",
                "error": (
                    f"negative usage delta for {self._agent_name}: "
                    f"last_input={last_input}, last_output={last_output}"
                ),
            }) if self._bus else None
            last_input = max(0, last_input)
            last_output = max(0, last_output)
            last_cache_hit = max(0, last_cache_hit)

        # Persist for node_factory to read after iter() completes (so the
        # final token_usage dict written into node.completed reflects the
        # last single-shot request, not just the cumulative iter total).
        self._last_input = last_input
        self._last_output = last_output
        self._last_cache_hit = last_cache_hit

        if self._bus:
            safe_emit(self._bus, "span.end", {
                "workflow_id": self._wid,
                "node_id": self._node_id,
                "agent_name": self._agent_name,
                "span_id": span_id,
                "span_type": "llm",
                "ts": int(time.time() * 1000),
            })

            # Per-LLM-request usage snapshot — drives BudgetBar's two bars:
            #   - Cost row uses cumulative_input + cumulative_output (cost view)
            #   - Window row uses last_input + last_output (context pressure)
            # Legacy input_tokens / output_tokens / total_tokens fields are
            # kept = cumulative for backward compat with older consumers.
            try:
                safe_emit(self._bus, "agent.usage_update", {
                    "workflow_id": self._wid,
                    "node_id": self._node_id,
                    "agent_name": self._agent_name,
                    "requests": getattr(ctx.state.usage, "requests", 0) or 0,
                    # Legacy fields (cumulative semantics — deprecated aliases
                    # for cumulative_input/output; kept for backward compat
                    # with pre-stage-2 consumers).
                    "input_tokens": current_input,
                    "output_tokens": current_output,
                    "total_tokens": current_input + current_output,
                    # Stage 2: explicit cumulative (numerically == legacy).
                    "cumulative_input": current_input,
                    "cumulative_output": current_output,
                    # Stage 2: per-request single-shot (most recent LLM call).
                    "last_input": last_input,
                    "last_output": last_output,
                    # Stage 2: cache hit split into cumulative + last for
                    # symmetry with input/output. `cache_hit` short alias
                    # kept for convenience but duplicates cumulative value.
                    "cumulative_cache_hit": current_cache_hit,
                    "last_cache_hit": last_cache_hit,
                    "cache_hit": current_cache_hit,
                }, priority="normal")
            except Exception:
                logger.debug("Failed to emit agent.usage_update", exc_info=True)

        return None

    def get_last_request_usage(self) -> dict[str, int]:
        """Return the most recent model request's single-shot usage.

        Read by node_factory after iter() completes so the persisted
        token_usage dict carries both cumulative and last-snapshot fields.
        Returns zeros if no model request has run yet.
        """
        return {
            "last_input": self._last_input,
            "last_output": self._last_output,
            "last_cache_hit": self._last_cache_hit,
        }

    # ------------------------------------------------------------------
    # Internal: call-tools node
    # ------------------------------------------------------------------

    async def _handle_call_tools(self, node, ctx) -> dict[str, Any] | None:
        """Execute tool calls, emit events, check interrupts."""
        # Pre-check before entering tool execution
        interrupt = self._poll_interrupt()
        if interrupt is not None:
            return interrupt

        # Pydantic AI yields ALL function_tool_call events upfront (before any tool
        # actually runs), then yields function_tool_result events as each tool
        # completes. Using the call-event timestamp as span.start would collapse
        # every tool's start to the same instant and inflate durations.
        # Instead, defer span.start to result time and back-date it to the previous
        # result's end (or the batch entry time for the first tool). Accurate for
        # sequential execution (the Pydantic AI default).
        if self._bus:
            tool_batch_start_ms = int(time.time() * 1000)
            last_end_ms = tool_batch_start_ms
            async with node.stream(ctx) as stream:
                async for event in stream:
                    interrupt = self._poll_interrupt()
                    if interrupt is not None:
                        return interrupt

                    ek = getattr(event, "event_kind", "")
                    if ek == "function_tool_call":
                        self._emit_tool_call(event.part)
                    elif ek == "function_tool_result":
                        self._emit_tool_result(event.part)
                        await self._fire_tool_call_hook(event.part)
                        now_ms = int(time.time() * 1000)
                        span_id = self._next_span_id()
                        safe_emit(self._bus, "span.start", {
                            "workflow_id": self._wid,
                            "node_id": self._node_id,
                            "agent_name": self._agent_name,
                            "span_id": span_id,
                            "span_type": "tool",
                            "tool_name": event.part.tool_name,
                            "ts": last_end_ms,
                        })
                        safe_emit(self._bus, "span.end", {
                            "workflow_id": self._wid,
                            "node_id": self._node_id,
                            "agent_name": self._agent_name,
                            "span_id": span_id,
                            "span_type": "tool",
                            "tool_name": event.part.tool_name,
                            "ts": now_ms,
                        })
                        last_end_ms = now_ms
        else:
            # No bus — still need interrupt checks
            async with node.stream(ctx) as stream:
                async for _ in stream:
                    interrupt = self._poll_interrupt()
                    if interrupt is not None:
                        return interrupt

        return None

    # ------------------------------------------------------------------
    # Interrupt checking
    # ------------------------------------------------------------------

    def _poll_interrupt(self) -> dict[str, Any] | None:
        """Check for a pending stop-and-regenerate signal.

        Returns the signal dict if found (and cancels any subprocess),
        or None if no interrupt is pending.
        """
        if self._check_interrupt is None:
            return None
        signal = self._check_interrupt(self._wid, self._agent_name)
        if signal is not None and self._cancel_fn is not None and self._wid:
            self._cancel_fn(self._wid)
        return signal

    # ------------------------------------------------------------------
    # Event emission helpers
    # ------------------------------------------------------------------

    def _emit_text_delta(self, delta: str) -> None:
        if not self._bus:
            return
        # Backpressure: when buffer >80% full, skip every other text_delta.
        # Usage of 0.0 (or missing/broken buffer_usage()) means no throttle.
        # Guard the entire read+compare so a bus that returns a non-numeric
        # value (e.g. a MagicMock in tests, or a broken implementation) fails
        # open (no throttle) rather than crashing the stream loop.
        over_threshold = False
        if hasattr(self._bus, "buffer_usage"):
            try:
                over_threshold = self._bus.buffer_usage() > 0.8
            except (TypeError, AttributeError):
                over_threshold = False
        if over_threshold:
            self._delta_skip_counter += 1
            if self._delta_skip_counter % 2 == 0:
                return
        safe_emit(self._bus, "agent.text_delta", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "text": delta,
        })

    def _emit_thinking_delta(self, delta: str) -> None:
        if not self._bus:
            return
        safe_emit(self._bus, "agent.thinking_delta", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "text": delta,
        })

    def _emit_tool_call(self, part) -> None:
        raw_args = part.args if hasattr(part, "args") else {}
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                raw_args = {"_raw": raw_args}
        if not isinstance(raw_args, dict):
            raw_args = {}

        tool_call_id = getattr(part, "tool_call_id", None)
        entry = {
            "tool_name": part.tool_name,
            "tool_args": raw_args,
            "tool_call_id": tool_call_id,
        }
        self.tool_calls.append(entry)
        if not self._bus:
            return
        payload_call: dict[str, Any] = {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "tool_args": raw_args,
        }
        if tool_call_id:
            payload_call["tool_call_id"] = tool_call_id
        safe_emit(self._bus, "agent.tool_call", payload_call)

    def _emit_tool_result(self, part) -> None:
        result_str = str(part.content) if hasattr(part, "content") else ""
        tool_call_id = getattr(part, "tool_call_id", None)
        # Match strictly by tool_call_id so parallel same-name calls do not have
        # their results crossed. If the ID is absent or no entry matches, log
        # and drop rather than land the result on the wrong call.
        matched = False
        if tool_call_id:
            for tc in reversed(self.tool_calls):
                if tc.get("tool_call_id") == tool_call_id and "tool_result" not in tc:
                    tc["tool_result"] = result_str
                    matched = True
                    break
        if not matched:
            logger.warning(
                "llm_executor: tool_result for tool_call_id=%s tool_name=%s had no "
                "matching tool_call (wf=%s node=%s) — dropped",
                tool_call_id, part.tool_name, self._wid, self._node_id,
            )
        if not self._bus:
            return
        payload_result: dict[str, Any] = {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "result": result_str,
        }
        if tool_call_id:
            payload_result["tool_call_id"] = tool_call_id
        safe_emit(self._bus, "agent.tool_result", payload_result)

    # ------------------------------------------------------------------
    # Extension hook helpers
    # ------------------------------------------------------------------

    async def _fire_llm_delta_hook(self, delta: str) -> None:
        if self._ext_ctx is None or self._bus is None:
            return
        if hasattr(self._bus, "run_hooks"):
            await self._bus.run_hooks("on_llm_delta", self._ext_ctx, delta)

    async def _fire_tool_call_hook(self, part) -> None:
        if self._ext_ctx is None or self._bus is None:
            return
        if hasattr(self._bus, "run_hooks"):
            # Reuse the normalized args stored by _emit_tool_call. Match by
            # tool_call_id so the hook sees the correct args when multiple
            # same-name calls are in flight; fall back to tool_name only if
            # the part lacks an ID (legacy pydantic-ai or synthetic events).
            tool_call_id = getattr(part, "tool_call_id", None)
            if tool_call_id:
                last_tc = next(
                    (tc for tc in reversed(self.tool_calls)
                     if tc.get("tool_call_id") == tool_call_id),
                    None,
                )
            else:
                last_tc = next(
                    (tc for tc in reversed(self.tool_calls)
                     if tc["tool_name"] == part.tool_name),
                    None,
                )
            tctx = ToolCtx(
                node=self._ext_ctx,
                tool_name=part.tool_name,
                tool_args=last_tc["tool_args"] if last_tc else {},
            )
            await self._bus.run_hooks(
                "on_tool_call",
                tctx,
                str(part.content) if hasattr(part, "content") else "",
            )
