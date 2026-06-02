"use client";

import {
  Scatter,
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
import { PALETTE, POSITIVE, NEUTRAL, LEGEND_STYLE, CHART_MARGIN, getGridProps, getAxisTick, getTooltipStyle } from "./chartTheme";
import { computeNiceTicks, formatTick } from "./axisUtils";

function computeOptimalLine(
  points: { x: number; y: number }[],
  direction: "max" | "min",
) {
  const sorted = [...points].sort((a, b) => a.x - b.x);
  let accum = sorted[0].y;
  return sorted.map((p) => {
    const prev = accum;
    accum = direction === "max" ? Math.max(accum, p.y) : Math.min(accum, p.y);
    return { x: p.x, y: accum, isNewRecord: accum !== prev };
  });
}

function OptimalDot(props: any) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null) return null;
  const isRecord = payload?.isRecord;
  const color = isRecord ? POSITIVE : NEUTRAL;
  const r = isRecord ? 4 : 3;
  return <circle cx={cx} cy={cy} r={r} fill={color} stroke="#fff" strokeWidth={1} />;
}

export default function OptimalLineChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title, optimal_line } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const direction = optimal_line ?? "max";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const points = data.map((d) => ({
    x: Number(d[xKey]),
    y: Number(d[yKey]),
  }));

  const xConfig = computeNiceTicks(points.map((p) => p.x));
  const yConfig = computeNiceTicks(points.map((p) => p.y));

  const optimalLine = computeOptimalLine(points, direction);
  const lineColor = direction === "max" ? PALETTE[0] : PALETTE[2];

  const merged = optimalLine.map((p, i) => ({
    x: p.x,
    scatter: points[i]?.y,
    optimal: p.y,
    isRecord: p.isNewRecord,
  }));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <ComposedChart data={merged} margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="x"
              tick={axisTick}
              name={xKey}
              type="number"
              domain={xConfig.domain}
              ticks={xConfig.ticks}
              tickFormatter={formatTick}
            />
            <YAxis
              tick={axisTick}
              domain={yConfig.domain}
              ticks={yConfig.ticks}
              tickFormatter={formatTick}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Scatter name="Data Points" dataKey="scatter" fill={NEUTRAL} fillOpacity={0.5} />
            <Line
              name={`Optimal (${direction})`}
              dataKey="optimal"
              stroke={lineColor}
              strokeWidth={2}
              dot={<OptimalDot />}
              type="stepAfter"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
