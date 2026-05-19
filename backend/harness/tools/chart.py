"""Chart tool for rendering visualizations via EventBus."""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory


class ChartToolFactory(ToolFactory):
    """chart tool — agent renders chart/table visualizations via EventBus."""

    name = "chart"
    description = (
        "Render a chart or table visualization. "
        "Parameters: data (list of row dicts), chart_type, x, y, label, title, hue. "
        "chart_type: 'line' | 'bar' | 'scatter' | 'pareto' | 'optimal_line' | 'heatmap' | 'box' | 'table'. "
        "For 'pareto': add pareto_direction='max' or 'min'. "
        "For 'optimal_line': add optimal_line='max' or 'min'."
    )

    def __init__(self, event_bus: Any | None = None):
        self.event_bus = event_bus

    def create(self) -> PydanticAITool:
        bus = self.event_bus

        async def chart(
            ctx: RunContext[AgentDeps],
            data: list[dict[str, Any]],
            chart_type: str,
            x: str | None = None,
            y: str | None = None,
            label: str = "default",
            title: str = "",
            hue: str | None = None,
            pareto_direction: str | None = None,
            optimal_line: str | None = None,
        ) -> str:
            # Derive columns from the data rows
            data_columns: list[str] = list(data[0].keys()) if data else []

            chart_payload: dict[str, Any] = {
                "chart_type": chart_type,
                "data": data,
                "columns": data_columns,
                "x": x,
                "y": y,
                "label": label,
                "title": title or chart_type,
                "hue": hue,
            }

            if chart_type == "pareto" and pareto_direction:
                chart_payload["pareto_direction"] = pareto_direction
            if chart_type == "optimal_line" and optimal_line:
                chart_payload["optimal_line"] = optimal_line

            if bus:
                bus.emit("chart.render", {
                    "node_id": ctx.deps.agent_name,
                    "agent_name": ctx.deps.agent_name,
                    "chart": chart_payload,
                })

            return f"Chart rendered: {chart_type} | label='{label}' | title='{title or chart_type}'"

        return PydanticAITool(chart, takes_ctx=True)
