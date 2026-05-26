"""AgentTracePlugin — emits trace.step events for every completed node.

Each on_node_end call produces a trace.step side effect with the agent
name, workflow ID, and status. Frontend consumes these to build
execution trace diagrams.
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class AgentTracePlugin(BaseHook):
    name = "agent-trace"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        ctx.emit("trace.step", {
            "workflow_id": ctx.workflow.workflow_id,
            "node_id": ctx.node_id,
            "agent_name": ctx.agent_name,
            "status": "completed",
        })