"""StepCounterPlugin — tracks tool calls, LLM calls, and retries per node/workflow.

Emits `step.summary` side effect on each node completion with accumulated counts.
"""

from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class StepCounterPlugin(BaseHook):
    name = "step-counter"

    def __init__(self):
        self._workflows: dict[str, dict] = {}

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        wid = ctx.workflow.workflow_id
        if wid not in self._workflows:
            self._workflows[wid] = {
                "nodes": {},
                "total_tool_calls": 0,
                "total_llm_calls": 0,
            }

        node_meta = ctx.metadata.get(ctx.agent_name, {})
        tool_calls = node_meta.get("tool_calls", [])

        tool_count = len(tool_calls)
        # Each node = at least 1 LLM call; tools may trigger additional reasoning
        llm_count = 1 + (1 if tool_count > 0 else 0)

        self._workflows[wid]["nodes"][ctx.agent_name] = {
            "tool_calls": tool_count,
            "llm_calls": llm_count,
        }
        self._workflows[wid]["total_tool_calls"] += tool_count
        self._workflows[wid]["total_llm_calls"] += llm_count

        ctx.emit("step.summary", {
            "workflow_id": wid,
            "node_id": ctx.agent_name,
            "node_tool_calls": tool_count,
            "node_llm_calls": llm_count,
            "total_tool_calls": self._workflows[wid]["total_tool_calls"],
            "total_llm_calls": self._workflows[wid]["total_llm_calls"],
        })

    def get_summary(self, workflow_id: str) -> dict:
        return self._workflows.get(workflow_id, {
            "nodes": {},
            "total_tool_calls": 0,
            "total_llm_calls": 0,
        })
