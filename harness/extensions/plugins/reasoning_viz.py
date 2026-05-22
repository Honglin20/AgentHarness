"""ReasoningVizPlugin — extracts chain-of-thought reasoning from messages.

Best-effort extraction of reasoning steps from assistant messages. Only
emits when a reasoning pattern is detected (e.g., "step by step",
numbered lists, "first/then/finally"). No-op otherwise.
"""
from __future__ import annotations

import re

from harness.extensions.base import BaseHook, NodeCtx

_REASONING_PATTERNS = [
    r"step\s+by\s+step",
    r"first,?.*then",
    r"\d+\.\s+",
    r"let me think",
    r"reasoning:",
]


class ReasoningVizPlugin(BaseHook):
    name = "reasoning-viz"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        steps = []
        for msg in ctx.messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if any(re.search(p, content, re.IGNORECASE) for p in _REASONING_PATTERNS):
                parts = re.split(r"(?=\d+\.\s)|(?<=[.!?])\s+", content)
                steps.extend([p.strip() for p in parts if p.strip()])

        if not steps:
            return

        ctx.emit("reasoning.render", {
            "workflow_id": ctx.workflow.workflow_id,
            "agent_name": ctx.agent_name,
            "steps": steps,
        })