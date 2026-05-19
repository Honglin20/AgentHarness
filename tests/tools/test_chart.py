"""Tests for chart tool."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import RunContext

from harness.tools.chart import ChartToolFactory
from harness.tools.deps import AgentDeps


def _make_ctx(agent_name: str = "test-agent") -> RunContext[AgentDeps]:
    deps = AgentDeps(agent_name=agent_name)
    return RunContext(
        deps=deps,
        model=None,
        usage=None,
        prompt=None,
    )


class MockEventBus:
    """Simple mock EventBus that records emitted events."""

    def __init__(self):
        self.events: list[dict] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.events.append({"type": event_type, "payload": payload})


class TestChartToolFactory:
    def test_chart_factory_name_and_description(self):
        """ChartToolFactory has correct name and description."""
        factory = ChartToolFactory(event_bus=None)

        assert factory.name == "chart"
        assert "chart_type" in factory.description

    def test_chart_factory_creates_tool(self):
        """ChartToolFactory.create() returns a PydanticAITool."""
        from pydantic_ai import Tool as PydanticAITool

        factory = ChartToolFactory(event_bus=None)
        tool = factory.create()

        assert isinstance(tool, PydanticAITool)
        assert tool.takes_ctx is True

    @pytest.mark.asyncio
    async def test_chart_emits_event(self):
        """Calling chart tool with EventBus emits a chart.render event."""
        bus = MockEventBus()
        factory = ChartToolFactory(event_bus=bus)
        tool = factory.create()
        chart_fn = tool.function

        data = [{"x": 1, "y": 4}, {"x": 2, "y": 5}, {"x": 3, "y": 6}]
        ctx = _make_ctx(agent_name="analyzer")

        result = await chart_fn(ctx, data=data, chart_type="bar", x="x", y="y")

        # Should have emitted one event
        assert len(bus.events) == 1
        event = bus.events[0]
        assert event["type"] == "chart.render"
        payload = event["payload"]
        assert payload["node_id"] == "analyzer"
        assert payload["agent_name"] == "analyzer"
        assert payload["chart"]["chart_type"] == "bar"

    @pytest.mark.asyncio
    async def test_chart_without_event_bus(self):
        """Calling chart tool without EventBus returns string, no error."""
        factory = ChartToolFactory(event_bus=None)
        tool = factory.create()
        chart_fn = tool.function

        data = [{"x": 1, "y": 3}, {"x": 2, "y": 4}]
        ctx = _make_ctx()

        result = await chart_fn(ctx, data=data, chart_type="line", x="x", y="y")

        assert isinstance(result, str)
        assert "line" in result
        assert "label='default'" in result

    @pytest.mark.asyncio
    async def test_chart_payload_structure(self):
        """Chart payload has required fields: chart_type, data, columns, x, y, label, title."""
        bus = MockEventBus()
        factory = ChartToolFactory(event_bus=bus)
        tool = factory.create()
        chart_fn = tool.function

        data = [{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 200}]
        ctx = _make_ctx()

        await chart_fn(
            ctx, data=data, chart_type="scatter",
            x="month", y="sales", label="q1", title="Q1 Sales",
        )

        chart = bus.events[0]["payload"]["chart"]
        assert chart["chart_type"] == "scatter"
        assert chart["data"] == [{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 200}]
        assert chart["columns"] == ["month", "sales"]
        assert chart["x"] == "month"
        assert chart["y"] == "sales"
        assert chart["label"] == "q1"
        assert chart["title"] == "Q1 Sales"
        assert chart["hue"] is None

    @pytest.mark.asyncio
    async def test_chart_pareto_direction(self):
        """When chart_type='pareto' and pareto_direction='max', payload includes it."""
        bus = MockEventBus()
        factory = ChartToolFactory(event_bus=bus)
        tool = factory.create()
        chart_fn = tool.function

        data = [{"category": "A", "value": 10}, {"category": "B", "value": 20}]
        ctx = _make_ctx()

        result = await chart_fn(
            ctx, data=data, chart_type="pareto",
            x="category", y="value", pareto_direction="max",
        )

        chart = bus.events[0]["payload"]["chart"]
        assert chart["chart_type"] == "pareto"
        assert chart["pareto_direction"] == "max"
        # Should NOT have optimal_line
        assert "optimal_line" not in chart

    @pytest.mark.asyncio
    async def test_chart_optimal_line(self):
        """When chart_type='optimal_line' and optimal_line='min', payload includes it."""
        bus = MockEventBus()
        factory = ChartToolFactory(event_bus=bus)
        tool = factory.create()
        chart_fn = tool.function

        data = [{"iter": 1, "loss": 0.5}, {"iter": 2, "loss": 0.3}, {"iter": 3, "loss": 0.1}]
        ctx = _make_ctx()

        result = await chart_fn(
            ctx, data=data, chart_type="optimal_line",
            x="iter", y="loss", optimal_line="min",
        )

        chart = bus.events[0]["payload"]["chart"]
        assert chart["chart_type"] == "optimal_line"
        assert chart["optimal_line"] == "min"
        # Should NOT have pareto_direction
        assert "pareto_direction" not in chart
