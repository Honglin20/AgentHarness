"""PerfMetricsPlugin — emits token usage bar chart on node end.

Reads token_usage and duration_ms from node metadata and emits a
bar chart visualization via ctx.emit().
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class PerfMetricsPlugin(BaseHook):
    name = "perf-metrics"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        node_meta = ctx.metadata.get(ctx.agent_name, {})
        token_usage = node_meta.get("token_usage")
        if not token_usage:
            return

        data = [{
            "agent": ctx.agent_name,
            "input_tokens": token_usage.get("input", 0),
            "output_tokens": token_usage.get("output", 0),
            "total_tokens": token_usage.get("total", 0),
        }]

        ctx.emit("chart.render", {
            "node_id": ctx.agent_name,
            "chart_type": "bar",
            "data": data,
            "x": "agent",
            "y": "total_tokens",
            "label": "Token Usage",
            "title": f"{ctx.agent_name} token usage",
        })