"""LLMExecutor — encapsulates the Pydantic AI agent iteration loop.

Extracted from MacroGraphBuilder._make_node_func() so that the core LLM
call + streaming + interrupt-checking logic lives in one focused class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic_graph import End

from harness.extensions.base import ToolCtx

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """What LLMExecutor.run() returns."""

    agent_run: Any  # pydantic_ai AgentRun
    stop_regen: dict[str, Any] | None = None


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
        self.tool_calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

        return AgentRunResult(agent_run=agent_run, stop_regen=stop_regen)

    # ------------------------------------------------------------------
    # Internal: model-request node (text streaming)
    # ------------------------------------------------------------------

    async def _handle_model_request(self, node, ctx) -> dict[str, Any] | None:
        """Stream model response text, emit deltas, check interrupts."""
        async with node.stream(ctx) as stream:
            prev_text = ""
            async for response in stream.stream_response():
                current_text = "".join(
                    p.content for p in response.parts
                    if getattr(p, "part_kind", None) == "text"
                )
                delta = current_text[len(prev_text):]
                prev_text = current_text

                if delta:
                    self._emit_text_delta(delta)
                    await self._fire_llm_delta_hook(delta)

                interrupt = self._poll_interrupt()
                if interrupt is not None:
                    return interrupt

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

        if self._bus:
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
        self._bus.emit("agent.text_delta", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "text": delta,
        })

    def _emit_tool_call(self, part) -> None:
        entry = {
            "tool_name": part.tool_name,
            "tool_args": part.args if hasattr(part, "args") else {},
        }
        self.tool_calls.append(entry)
        if not self._bus:
            return
        self._bus.emit("agent.tool_call", {
            "workflow_id": self._wid,
            "node_id": self._node_id,
            "agent_name": self._agent_name,
            "tool_name": part.tool_name,
            "tool_args": entry["tool_args"],
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
        self._bus.emit("agent.tool_result", {
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
            tctx = ToolCtx(
                node=self._ext_ctx,
                tool_name=part.tool_name,
                tool_args={},
            )
            await self._bus.run_hooks(
                "on_tool_call",
                tctx,
                str(part.content) if hasattr(part, "content") else "",
            )
