"""CircularDetectorPlugin — detects repeated/identical tool call sequences.

Monitors tool calls per node. If the last N consecutive calls are identical
(same tool_name + same args), emits a circular.warning side effect.
"""

from __future__ import annotations

import json
from harness.extensions.base import BaseHook, NodeCtx


class CircularDetectorPlugin(BaseHook):
    name = "circular-detector"

    def __init__(self, threshold: int = 3):
        self._threshold = threshold

    def _signature(self, tool_call: dict) -> str:
        """Create a stable signature for a tool call."""
        return json.dumps({
            "tool_name": tool_call.get("tool_name", ""),
            "tool_args": tool_call.get("tool_args", {}),
        }, sort_keys=True)

    def _is_circular(self, tool_calls: list[dict]) -> bool:
        """Check if the last N tool calls are identical."""
        if len(tool_calls) < self._threshold:
            return False
        tail = tool_calls[-self._threshold:]
        first_sig = self._signature(tail[0])
        return all(self._signature(tc) == first_sig for tc in tail)

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        node_meta = ctx.metadata.get(ctx.agent_name, {})
        tool_calls = node_meta.get("tool_calls", [])

        if self._is_circular(tool_calls):
            ctx.emit("circular.warning", {
                "workflow_id": ctx.workflow.workflow_id,
                "node_id": ctx.agent_name,
                "agent_name": ctx.agent_name,
                "repeated_count": self._threshold,
                "last_tool": tool_calls[-1].get("tool_name") if tool_calls else None,
                "message": f"Detected {self._threshold}+ identical consecutive tool calls on '{tool_calls[-1].get('tool_name', '')}'",
            })
