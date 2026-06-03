"""EvalChartPlugin — emits line chart for judge evaluation scores.

Triggered on on_node_end for nodes named _judge_*. Reads score_history
from metadata and emits a chart.render side effect via ctx.emit().
"""
from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class EvalChartPlugin(BaseHook):
    name = "eval-chart"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        if not ctx.agent_name.startswith("_judge_"):
            return

        score = getattr(output, "score", None)
        if score is None:
            return

        # Accumulate score history in the agent's metadata namespace.
        # _make_node_func seeds prior score_history from LangGraph state
        # (so it persists across retry iterations) and merges it back after
        # hooks, completing the persistence cycle.
        node_meta = ctx.metadata.setdefault(ctx.agent_name, {})
        prior_history = list(node_meta.get("score_history", []))
        prior_history.append(score)
        node_meta["score_history"] = prior_history

        target_name = ctx.agent_name.replace("_judge_", "")
        ctx.emit("chart.render", {
            "node_id": ctx.agent_name,
            "chart_type": "line",
            "data": [{"iteration": i + 1, "score": s} for i, s in enumerate(prior_history)],
            "x": "iteration",
            "y": "score",
            "label": "Eval Scores",
            "title": f"{target_name} quality",
            "category": "analysis",
        })