"""render_chart as a Pydantic AI tool — agents can call it directly."""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.chart import render_chart
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory


class ChartToolFactory(ToolFactory):
    """Tool factory that wraps render_chart() as a Pydantic AI tool."""

    name = "render_chart"
    description = (
        "Render a chart or table to the frontend UI. "
        "Use this to visualize data for the user. "
        "Supported chart types: line, bar, scatter, pareto, optimal_line, heatmap, box, table."
    )

    def create(self) -> PydanticAITool:
        async def chart(
            ctx: RunContext[AgentDeps],
            chart_type: str,
            data: list[dict[str, Any]],
            x: str = "",
            y: str = "",
            label: str = "default",
            title: str = "",
            hue: str = "",
        ) -> str:
            return render_chart(
                data=data,
                chart_type=chart_type,
                x=x or None,
                y=y or None,
                label=label,
                title=title,
                hue=hue or None,
                node_id=ctx.deps.agent_name,
            )

        return PydanticAITool(chart, takes_ctx=True)
