"""render_chart function — code-callable chart rendering with dual-channel delivery.

This is NOT a Pydantic AI tool. Agent code calls it directly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

_CHART_ENDPOINT = "/api/charts"
_CHART_STDOUT_PREFIX = "__HARNESS_CHART__:"


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
    size: str | None = None,
    pareto_direction: str | None = None,
    pareto_x_direction: str | None = None,
    pareto_y_direction: str | None = None,
    optimal_line: str | None = None,
    node_id: str = "",
) -> str:
    """Render a chart or table visualization to the frontend.

    Delivery channels (tried in order):
      1. EventBus (same server process) — zero latency
      2. Stdout capture — bash tool's _reader detects the chart marker
         and emits via EventBus. Works from any subprocess, no env vars.
      3. HTTP POST /api/charts — last resort for non-bash environments.

    Args:
        data: Row dicts (equivalent to DataFrame.to_dict("records")).
        chart_type: "line" | "bar" | "scatter" | "pareto" | "optimal_line"
                    | "heatmap" | "box" | "bubble" | "area" | "radar"
                    | "table"
        x: X-axis column name.
        y: Y-axis column name.
        label: Group label for frontend collapsible sections.
        title: Chart title. Same label+title replaces existing chart (live update).
        hue: Color-grouping column name.
        size: Bubble size column name (only for chart_type="bubble").
        pareto_direction: "max" or "min" (only for chart_type="pareto").
        pareto_x_direction: "max" or "min" — override x-axis direction for pareto.
        pareto_y_direction: "max" or "min" — override y-axis direction for pareto.
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

    if chart_type == "pareto":
        if pareto_direction:
            chart_payload["pareto_direction"] = pareto_direction
        if pareto_x_direction:
            chart_payload["pareto_x_direction"] = pareto_x_direction
        if pareto_y_direction:
            chart_payload["pareto_y_direction"] = pareto_y_direction
    if chart_type == "optimal_line" and optimal_line:
        chart_payload["optimal_line"] = optimal_line
    if chart_type == "bubble" and size:
        chart_payload["size"] = size

    event_payload = {
        "node_id": node_id,
        "agent_name": node_id,
        "chart": chart_payload,
    }
    rendered_msg = f"Chart rendered: {chart_type} | label='{label}' | title='{title or chart_type}'"

    # Channel 1: EventBus (same-process — only if active server instance)
    bus = _try_get_event_bus()
    if bus and bus.subscriber_count > 0:
        bus.emit("chart.render", event_payload)
        return rendered_msg

    # Channel 2: Stdout capture — bash tool _reader detects __HARNESS_CHART__:
    # prefix and emits chart.render via the workflow's EventBus. Works from
    # any subprocess spawned by the bash tool, regardless of env vars.
    print(f"{_CHART_STDOUT_PREFIX}{json.dumps(event_payload)}", flush=True)

    # Channel 3: HTTP POST (last resort — for non-bash subprocesses)
    server_url = os.environ.get("HARNESS_SERVER_URL")
    if server_url:
        url = f"{server_url.rstrip('/')}{_CHART_ENDPOINT}"
        _http_post(url, {"node_id": node_id, "chart": chart_payload})

    return rendered_msg
