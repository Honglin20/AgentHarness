"""Tests for render_chart — plain function with dual-channel delivery."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from harness.tools.chart import render_chart


class MockEventBus:
    """Simple mock EventBus that records emitted events."""

    def __init__(self):
        self.events: list[dict] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.events.append({"type": event_type, "payload": payload})


@pytest.fixture
def sample_data():
    return [{"x": 1, "y": 4}, {"x": 2, "y": 5}, {"x": 3, "y": 6}]


class TestRenderChartEventBus:
    """Tests for EventBus channel (same process)."""

    def test_emits_event_via_event_bus(self, monkeypatch, sample_data):
        """render_chart emits chart.render via EventBus when available."""
        bus = MockEventBus()

        def _mock_get_event_bus():
            return bus

        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", _mock_get_event_bus
        )

        result = render_chart(
            data=sample_data, chart_type="bar", x="x", y="y", node_id="analyzer"
        )

        assert len(bus.events) == 1
        event = bus.events[0]
        assert event["type"] == "chart.render"
        assert event["payload"]["node_id"] == "analyzer"
        assert event["payload"]["agent_name"] == "analyzer"
        assert event["payload"]["chart"]["chart_type"] == "bar"
        assert "bar" in result

    def test_payload_structure(self, monkeypatch, sample_data):
        """Chart payload has all required fields."""
        bus = MockEventBus()
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: bus
        )

        render_chart(
            data=[{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 200}],
            chart_type="scatter",
            x="month", y="sales", label="q1", title="Q1 Sales",
            node_id="test",
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

    def test_pareto_direction(self, monkeypatch):
        """chart_type='pareto' includes pareto_direction."""
        bus = MockEventBus()
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: bus
        )

        render_chart(
            data=[{"category": "A", "value": 10}],
            chart_type="pareto", x="category", y="value",
            pareto_direction="max",
        )

        chart = bus.events[0]["payload"]["chart"]
        assert chart["chart_type"] == "pareto"
        assert chart["pareto_direction"] == "max"
        assert "optimal_line" not in chart

    def test_optimal_line(self, monkeypatch):
        """chart_type='optimal_line' includes optimal_line."""
        bus = MockEventBus()
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: bus
        )

        render_chart(
            data=[{"iter": 1, "loss": 0.5}, {"iter": 2, "loss": 0.3}],
            chart_type="optimal_line", x="iter", y="loss",
            optimal_line="min",
        )

        chart = bus.events[0]["payload"]["chart"]
        assert chart["chart_type"] == "optimal_line"
        assert chart["optimal_line"] == "min"
        assert "pareto_direction" not in chart

    def test_empty_data(self, monkeypatch):
        """Empty data produces empty columns."""
        bus = MockEventBus()
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: bus
        )

        render_chart(data=[], chart_type="table", label="empty")

        chart = bus.events[0]["payload"]["chart"]
        assert chart["columns"] == []
        assert chart["data"] == []

    def test_title_fallback(self, monkeypatch):
        """When title is empty, falls back to chart_type."""
        bus = MockEventBus()
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: bus
        )

        render_chart(data=[{"a": 1}], chart_type="line", title="")

        chart = bus.events[0]["payload"]["chart"]
        assert chart["title"] == "line"


class TestRenderChartHTTP:
    """Tests for HTTP fallback channel (subprocess / external)."""

    @pytest.fixture(autouse=True)
    def clear_env(self):
        """Clear HARNESS_SERVER_URL before each test."""
        old = os.environ.pop("HARNESS_SERVER_URL", None)
        yield
        if old is not None:
            os.environ["HARNESS_SERVER_URL"] = old

    def test_http_fallback_used_when_no_event_bus(self, monkeypatch, sample_data):
        """When EventBus unavailable, uses HTTP POST to HARNESS_SERVER_URL."""
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: None
        )
        os.environ["HARNESS_SERVER_URL"] = "http://localhost:1234"

        captured: dict[str, Any] = {}

        def fake_http_post(url, payload):
            captured["url"] = url
            captured["payload"] = payload
            return True

        monkeypatch.setattr(
            "harness.tools.chart._http_post", fake_http_post
        )

        result = render_chart(
            data=sample_data, chart_type="line", x="x", y="y", node_id="test"
        )

        assert captured["url"] == "http://localhost:1234/api/charts"
        assert captured["payload"]["chart"]["chart_type"] == "line"
        assert "line" in result

    def test_http_fallback_strips_trailing_slash(self, monkeypatch, sample_data):
        """HARNESS_SERVER_URL with trailing slash works correctly."""
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: None
        )
        os.environ["HARNESS_SERVER_URL"] = "http://localhost:8001/"

        captured: dict[str, Any] = {}

        def fake_http_post(url, payload):
            captured["url"] = url
            return True

        monkeypatch.setattr(
            "harness.tools.chart._http_post", fake_http_post
        )

        render_chart(data=[{"a": 1}], chart_type="bar", x="a")

        assert captured["url"] == "http://localhost:8001/api/charts"

    def test_http_fallback_failure(self, monkeypatch, sample_data):
        """Failed HTTP POST returns error message."""
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: None
        )
        os.environ["HARNESS_SERVER_URL"] = "http://localhost:9999"

        monkeypatch.setattr(
            "harness.tools.chart._http_post", lambda url, payload: False
        )

        result = render_chart(
            data=sample_data, chart_type="bar", x="x", y="y"
        )

        assert "failed" in result.lower()


class TestRenderChartNoChannel:
    """Tests for no-channel fallback."""

    def test_no_event_bus_no_api_url(self, monkeypatch, sample_data):
        """When neither EventBus nor HARNESS_SERVER_URL is available, returns info message."""
        monkeypatch.setattr(
            "harness.tools.chart._try_get_event_bus", lambda: None
        )
        # No HARNESS_SERVER_URL in env
        os.environ.pop("HARNESS_SERVER_URL", None)

        result = render_chart(
            data=sample_data, chart_type="line", x="x", y="y"
        )

        assert "not rendered" in result.lower()
