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
  const lineColor = direction === "max" ? "#3B82F6" : "#EF4444";

  // Merge scatter and line data for ComposedChart
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
          <ComposedChart data={merged} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="x" tick={{ fontSize: 11, fill: "#6B7280" }} name={xKey} />
            <YAxis tick={{ fontSize: 11, fill: "#6B7280" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "white",
                borderRadius: 6,
                border: "1px solid #E5E7EB",
                fontSize: 12,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Scatter name="Data Points" dataKey="scatter" fill="#9CA3AF" fillOpacity={0.6} />
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
