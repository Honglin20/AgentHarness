"""render_chart function — code-callable chart rendering with dual-channel delivery.

This is NOT a Pydantic AI tool. Agent code calls it directly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_CHART_ENDPOINT = "/api/charts"


def _try_get_event_bus():
    """Try to get the process-level singleton EventBus. Returns None if unavailable."""
    try:
        from server.event_bus import get_event_bus

        return get_event_bus()
    except Exception:
        return None


def _http_post(url: str, payload: dict) -> bool:
    """POST chart payload to the API endpoint. Returns True on success."""
    try:
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        logger.warning(f"Failed to POST chart to {url}: {e}")
        return False


def render_chart(
    data: list[dict[str, Any]],
    chart_type: str,
    x: str | None = None,
    y: str | None = None,
    label: str = "default",
    title: str = "",
    hue: str | None = None,
    pareto_direction: str | None = None,
    optimal_line: str | None = None,
    node_id: str = "",
) -> str:
    """Render a chart or table visualization to the frontend.

    Dual-channel delivery:
      1. EventBus (same process) — preferred, zero latency
      2. HTTP POST /api/charts — for subprocess or remote execution

    Args:
        data: Row dicts (equivalent to DataFrame.to_dict("records")).
        chart_type: "line" | "bar" | "scatter" | "pareto" | "optimal_line"
                    | "heatmap" | "box" | "table"
        x: X-axis column name.
        y: Y-axis column name.
        label: Group label for frontend collapsible sections.
        title: Chart title. Same label+title replaces existing chart (live update).
        hue: Color-grouping column name.
        pareto_direction: "max" or "min" (only for chart_type="pareto").
        optimal_line: "max" or "min" (only for chart_type="optimal_line").
        node_id: Identifier of the calling agent/node.

    Returns:
        Confirmation string describing what was rendered.
    """
    columns: list[str] = list(data[0].keys()) if data else []

    chart_payload: dict[str, Any] = {
        "chart_type": chart_type,
        "data": data,
        "columns": columns,
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

    event_payload = {
        "node_id": node_id,
        "agent_name": node_id,
        "chart": chart_payload,
    }

    # Channel 1: EventBus (same process)
    bus = _try_get_event_bus()
    if bus:
        bus.emit("chart.render", event_payload)
        return f"Chart rendered: {chart_type} | label='{label}' | title='{title or chart_type}'"

    # Channel 2: HTTP POST (subprocess / external script)
    api_url = os.environ.get("HARNESS_API_URL")
    if api_url:
        url = f"{api_url.rstrip('/')}{_CHART_ENDPOINT}"
        ok = _http_post(url, {"node_id": node_id, "chart": chart_payload})
        if ok:
            return f"Chart rendered: {chart_type} | label='{label}' | title='{title or chart_type}'"
        return f"Chart failed to render: could not reach {url}"

    return (
        f"Chart not rendered: no event bus or API URL available. "
        f"Set HARNESS_API_URL environment variable or run inside the server process."
    )
