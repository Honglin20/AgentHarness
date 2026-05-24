"use client";

import {
  ScatterChart,
  Scatter,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  ComposedChart,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, NEUTRAL, AXIS_TICK, TOOLTIP_STYLE, LEGEND_STYLE, CHART_MARGIN, GRID_PROPS } from "./chartTheme";

function computeOptimalLine(
  points: { x: number; y: number }[],
  direction: "max" | "min",
) {
  const sorted = [...points].sort((a, b) => a.x - b.x);
  let accum = sorted[0].y;
  return sorted.map((p) => {
    accum = direction === "max" ? Math.max(accum, p.y) : Math.min(accum, p.y);
    return { x: p.x, y: accum };
  });
}

export default function OptimalLineChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title, optimal_line } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const direction = optimal_line ?? "max";

  const points = data.map((d) => ({
    x: Number(d[xKey]),
    y: Number(d[yKey]),
  }));

  const optimalLine = computeOptimalLine(points, direction);
  const lineColor = direction === "max" ? PALETTE[0] : PALETTE[2];

  const merged = points.map((p, i) => ({
    x: p.x,
    scatter: p.y,
    optimal: optimalLine[i]?.y,
  }));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={merged} margin={CHART_MARGIN}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey="x" tick={AXIS_TICK} name={xKey} />
            <YAxis tick={AXIS_TICK} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Scatter name="Data Points" dataKey="scatter" fill={NEUTRAL} fillOpacity={0.5} />
            <Line
              name={`Optimal (${direction})`}
              dataKey="optimal"
              stroke={lineColor}
              strokeWidth={2}
              dot={false}
              type="stepAfter"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
