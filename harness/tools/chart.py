"""render_chart function — code-callable chart rendering with dual-channel delivery.

Also provides RenderChartToolFactory so agents can call render_chart as a Pydantic AI tool.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from pydantic_ai import RunContext

from harness.tools.registry import ToolFactory

logger = logging.getLogger(__name__)

_CHART_ENDPOINT = "/api/charts"
_CHART_STDOUT_PREFIX = "__HARNESS_CHART__:"
_VALID_CHART_TYPES = {
    "line", "bar", "scatter", "pareto", "optimal_line",
    "heatmap", "box", "bubble", "area", "radar", "table", "waterfall",
    "dist_overlay",
}


def _validate_chart(
    data: list[dict[str, Any]],
    chart_type: str,
    x: str | None,
    y: str | None,
    hue: str | None,
    size: str | None,
    series: list[dict[str, Any]] | None = None,
) -> None:
    """Validate chart parameters. Raises ValueError with a clear message."""
    if chart_type not in _VALID_CHART_TYPES:
        raise ValueError(
            f"Invalid chart_type '{chart_type}'. Must be one of: {sorted(_VALID_CHART_TYPES)}"
        )

    if not data:
        raise ValueError("data cannot be empty")

    columns = list(data[0].keys())

    def _col_exists(col: str, label: str) -> None:
        if col not in columns:
            raise ValueError(
                f"{label} column '{col}' not found in data. Available columns: {columns}"
            )

    def _all_numeric(col: str, label: str) -> None:
        for i, row in enumerate(data):
            try:
                float(row[col])
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label} column '{col}' has non-numeric value at row {i}: {row[col]!r}"
                )

    xKey = x or "x"
    yKey = y or "y"

    if chart_type == "table":
        return

    # scatter / pareto / optimal_line: x and y must be numeric
    if chart_type in ("scatter", "pareto", "optimal_line"):
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        _all_numeric(xKey, "x")
        _all_numeric(yKey, "y")

    if chart_type == "optimal_line" and len(data) < 2:
        raise ValueError("optimal_line requires at least 2 data points")

    # heatmap: needs value/v column, x/y unique limits
    if chart_type == "heatmap":
        val_col = next((c for c in ("value", "v") if c in columns), None)
        if val_col is None:
            raise ValueError(
                f"heatmap requires a 'value' or 'v' column. Available columns: {columns}"
            )
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        x_unique = len({str(r[xKey]) for r in data})
        y_unique = len({str(r[yKey]) for r in data})
        if x_unique > 50:
            raise ValueError(
                f"heatmap x-axis has {x_unique} unique values (max 50). Consider grouping."
            )
        if y_unique > 50:
            raise ValueError(
                f"heatmap y-axis has {y_unique} unique values (max 50). Consider grouping."
            )

    # bubble: needs size
    if chart_type == "bubble":
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        size_key = size or "size"
        _col_exists(size_key, "size")
        _all_numeric(xKey, "x")
        _all_numeric(yKey, "y")
        for i, row in enumerate(data):
            v = row.get(size_key, 0)
            try:
                if float(v) <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError(
                    f"size column '{size_key}' must be positive at row {i}: {v!r}"
                )

    # area with hue: validate multi-category
    if chart_type == "area" and hue:
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        _col_exists(hue, "hue")
        hue_vals = {str(r[hue]) for r in data}
        if len(hue_vals) < 2:
            raise ValueError(
                f"area with hue requires >= 2 distinct hue values, got {len(hue_vals)}: {hue_vals}"
            )
        x_per_hue: dict[str, set[str]] = {}
        for r in data:
            hv = str(r[hue])
            x_per_hue.setdefault(hv, set()).add(str(r[xKey]))
        for hv, xs in x_per_hue.items():
            if len(xs) < 2:
                raise ValueError(
                    f"area with hue: hue value '{hv}' has only {len(xs)} x point(s). "
                    f"Each hue category needs >= 2 x values to form an area."
                )

    # box: need enough numeric values
    if chart_type == "box":
        numeric_cols = [
            c for c in columns
            if c != xKey and all(
                isinstance(r.get(c), (int, float)) or _is_number(r.get(c))
                for r in data
            )
        ]
        total_values = sum(
            len([r for r in data if _is_number(r.get(c))]) for c in numeric_cols
        )
        if total_values < 3:
            raise ValueError(
                f"box plot needs >= 3 numeric values across columns, got {total_values}. "
                f"Numeric columns found: {numeric_cols}"
            )

    # radar: need >= 3 dimensions
    if chart_type == "radar":
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        dims = {str(r[xKey]) for r in data}
        if len(dims) < 3:
            raise ValueError(
                f"radar chart needs >= 3 distinct dimension (x) values, got {len(dims)}: {dims}"
            )

    # line/bar with hue
    if chart_type in ("line", "bar") and hue:
        _col_exists(xKey, "x")
        _col_exists(yKey, "y")
        _col_exists(hue, "hue")

    # dist_overlay: requires series config with valid keys
    if chart_type == "dist_overlay":
        _col_exists(xKey, "x")
        if not data:
            raise ValueError("dist_overlay requires data")
        columns_set = set(data[0].keys())
        for i, s in enumerate(series or []):
            if not isinstance(s, dict) or "key" not in s:
                raise ValueError(
                    f"dist_overlay series[{i}] must be a dict with 'key' field"
                )
            skey = s["key"]
            if skey not in columns_set:
                raise ValueError(
                    f"dist_overlay series[{i}].key '{skey}' not in data columns: {sorted(columns_set)}"
                )
            stype = s.get("type", "area")
            if stype not in ("area", "line"):
                raise ValueError(
                    f"dist_overlay series[{i}].type must be 'area' or 'line', got '{stype}'"
                )
            if stype == "area" or stype == "line":
                _all_numeric(skey, f"series[{i}].key")
        if not series:
            raise ValueError("dist_overlay requires 'series' parameter")


def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False


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
    series: list[dict[str, Any]] | None = None,
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
                    | "table" | "waterfall" | "dist_overlay"
        x: X-axis column name.
        y: Y-axis column name.
        label: Group label for frontend collapsible sections.
        title: Chart title. Same label+title replaces existing chart (live update).
        hue: Color-grouping column name.
        size: Bubble size column name (only for chart_type="bubble").
        series: Series definitions for dist_overlay. Each entry is a dict:
            - key (required): column name in data
            - type: "area" or "line" (default "area")
            - axis: "left" or "right" (default "left")
            - color: hex color override (default from PALETTE)
            - fillOpacity: 0-1 for area fill (default 0.2)
            - dash: stroke-dasharray for line (e.g. "6 3")
            - step: use step interpolation (default False)
            - label: legend display name (defaults to key)
            - strokeWidth: line width (default 1.5)
        pareto_direction: "max" or "min" (only for chart_type="pareto").
        pareto_x_direction: "max" or "min" — override x-axis direction for pareto.
        pareto_y_direction: "max" or "min" — override y-axis direction for pareto.
        optimal_line: "max" or "min" (only for chart_type="optimal_line").
        node_id: Identifier of the calling agent/node.

    Returns:
        Confirmation string describing what was rendered.
    """
    _validate_chart(data, chart_type, x, y, hue, size, series=series)

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
    if chart_type == "dist_overlay" and series:
        chart_payload["series"] = series

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


# ---------------------------------------------------------------------------
# Pydantic AI Tool wrapper
# ---------------------------------------------------------------------------

class RenderChartToolFactory(ToolFactory):
    """ToolFactory that exposes render_chart as a Pydantic AI agent tool."""

    name = "render_chart"
    description = (
        "Render a chart visualization (bar, line, scatter, heatmap, etc.) to the frontend. "
        "Use this to visualize data analysis results. The chart will appear inline in the "
        "conversation AND in the Results tab.\n\n"
        "Args:\n"
        "  data: List of row dicts (e.g. [{'month':'Jan','sales':100}, ...]).\n"
        "  chart_type: 'line' | 'bar' | 'scatter' | 'pareto' | 'optimal_line' | 'heatmap' "
        "| 'box' | 'bubble' | 'area' | 'radar' | 'table' | 'waterfall' | 'dist_overlay'.\n"
        "  x: X-axis column name.\n"
        "  y: Y-axis column name.\n"
        "  label: Group label for collapsible sections (default 'default').\n"
        "  title: Chart title.\n"
        "  hue: Color-grouping column.\n"
        "  size: Bubble size column (chart_type='bubble' only).\n"
        "  series: Series definitions for dist_overlay. Each entry: "
        "{'key': col_name, 'type': 'area'|'line', 'axis': 'left'|'right', "
        "'color': '#hex', 'fillOpacity': 0.2, 'dash': '6 3', 'step': false, "
        "'label': 'display name', 'strokeWidth': 1.5}.\n"
    )

    def __init__(self, event_bus=None):
        self.event_bus = event_bus

    def create(self):
        def render_chart_tool(
            ctx: RunContext,
            data: list[dict[str, Any]],
            chart_type: str,
            x: str | None = None,
            y: str | None = None,
            label: str = "default",
            title: str = "",
            hue: str | None = None,
            size: str | None = None,
            series: list[dict[str, Any]] | None = None,
            pareto_direction: str | None = None,
            optimal_line: str | None = None,
        ) -> str:
            node_id = getattr(ctx.deps, "node_id", "") if ctx.deps else ""
            return render_chart(
                data=data,
                chart_type=chart_type,
                x=x,
                y=y,
                label=label,
                title=title,
                hue=hue,
                size=size,
                series=series,
                pareto_direction=pareto_direction,
                optimal_line=optimal_line,
                node_id=node_id,
            )

        from pydantic_ai import Tool as PydanticAITool
        return PydanticAITool(self._wrap_fn(render_chart_tool, "render_chart"), name="render_chart", takes_ctx=True, description=self.description)
