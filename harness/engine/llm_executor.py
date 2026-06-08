"""LLMExecutor — encapsulates the Pydantic AI agent iteration loop.

Extracted from MacroGraphBuilder._make_node_func() so that the core LLM
call + streaming + interrupt-checking logic lives in one focused class.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic_graph import End
from pydantic_ai.messages import ModelRequest, SystemPromptPart

from harness.extensions.base import ToolCtx
from harness.extensions.bus import safe_emit
from harness.engine.token_aggregator import TokenAggregator

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """What LLMExecutor.run() returns."""

    agent_run: Any  # pydantic_ai AgentRun
    stop_regen: dict[str, Any] | None = None
    ttft_ms: int | None = None


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
        reminder_tracker: Any | None = None,
        token_aggregator: TokenAggregator | None = None,
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
        self._reminder_tracker = reminder_tracker
        self._token_aggregator = token_aggregator
        self.tool_calls: list[dict[str, Any]] = []
        self._span_seq = 0
        self._last_ttft_ms: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _next_span_id(self) -> str:
        self._span_seq += 1
        return f"{self._node_id}-s{self._span_seq}"

    async def run(self, context: str) -> AgentRunResult:
        """Execute the agent and return the result.

        Handles:
        - iter() loop with streaming text deltas
        - tool_call / tool_result event emission
        - interrupt (stop-and-regenerate) detection at every iteration step
        """
        stop_regen: dict[str, Any] | None = None

        async with self._agent.iter(context, deps=self._deps) as agent_run:
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

        # Inject reminder as a system message into message_history before the
        # model call.  This is read by pydantic-ai's _prepare_request() inside
        # node.stream(ctx), so the LLM sees it — but we never mutate event
        # objects from the tool-execution phase.
        if self._reminder_tracker:
            reminder = self._reminder_tracker.get_reminder()
            if reminder:
                ctx.state.message_history.append(
                    ModelRequest(parts=[SystemPromptPart(content=reminder)])
                )

        span_id = self._next_span_id()
        model_name = ""
        if hasattr(self._agent, "model"):
            m = self._agent.model
            model_name = str(getattr(m, "model_name", m) if hasattr(m, "model_name") else m)

        if self._bus:
            safe_emit(self._bus,"span.start", {
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

        if self._bus:
            safe_emit(self._bus,"span.end", {
                "workflow_id": self._wid,
                "node_id": self._node_id,
                "agent_name": self._agent_name,
                "span_id": span_id,
                "span_type": "llm",
                "ts": int(time.time() * 1000),
            })

        return None

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
                        if self._reminder_tracker:
                            self._reminder_tracker.on_tool_call(event.part.tool_name)
                    elif ek == "function_tool_result":
                        self._emit_tool_result(event.part)
                        await self._fire_tool_call_hook(event.part)
                        now_ms = int(time.time() * 1000)
                        span_id = self._next_span_id()
                        safe_emit(self._bus,"span.start", {
                            "workflow_id": self._wid,
                            "node_id": self._node_id,
                            "agent_name": self._agent_name,
                            "span_id": span_id,
                            "span_type": "tool",
                            "tool_name": event.part.tool_name,
                            "ts": last_end_ms,
                        })
                        safe_emit(self._bus,"span.end", {
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
        safe_emit(self._bus,"agent.text_delta", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "text": delta,
        })

    def _emit_thinking_delta(self, delta: str) -> None:
        if not self._bus:
            return
        safe_emit(self._bus,"agent.thinking_delta", {
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

        entry = {
            "tool_name": part.tool_name,
            "tool_args": raw_args,
        }
        self.tool_calls.append(entry)
        if not self._bus:
            return
        safe_emit(self._bus,"agent.tool_call", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "tool_args": raw_args,
        })

    def _emit_tool_result(self, part) -> None:
        result_str = str(part.content) if hasattr(part, "content") else ""
        # Attach result to the last unmatched tool_call entry
        for tc in reversed(self.tool_calls):
            if tc["tool_name"] == part.tool_name and "tool_result" not in tc:
                tc["tool_result"] = result_str
                break
        if not self._bus:
            return
        safe_emit(self._bus,"agent.tool_result", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "result": result_str,
        })

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
            # Reuse the normalized args stored by _emit_tool_call
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
