"""PerfMetricsPlugin — emits a combined token usage bar chart across all agents.

Reads token_usage and duration_ms from node metadata, accumulates across
nodes, and emits a single grouped bar chart with hue=kind (input/output/total).
"""

from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class PerfMetricsPlugin(BaseHook):
    name = "perf-metrics"

    def __init__(self):
        self._accumulated: list[dict] = []

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        node_meta = ctx.metadata.get(ctx.agent_name, {})
        token_usage = node_meta.get("token_usage")
        if not token_usage:
            return

        self._accumulated.append({
            "agent": ctx.agent_name,
            "input_tokens": token_usage.get("input", 0),
            "output_tokens": token_usage.get("output", 0),
            "total_tokens": token_usage.get("total", 0),
        })

        # Build grouped data: one row per agent per kind
        data: list[dict] = []
        for entry in self._accumulated:
            data.append({"agent": entry["agent"], "kind": "input", "tokens": entry["input_tokens"]})
            data.append({"agent": entry["agent"], "kind": "output", "tokens": entry["output_tokens"]})

        ctx.emit("chart.render", {
            "node_id": ctx.agent_name,
            "chart_type": "bar",
            "data": data,
            "columns": ["agent", "kind", "tokens"],
            "x": "agent",
            "y": "tokens",
            "hue": "kind",
            "label": "Token Usage",
            "title": "Token Usage by Agent",
            "category": "analysis",
        })
