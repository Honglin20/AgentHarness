"use client";

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  ZAxis,
} from "recharts";
import type { ChartPayload } from "@/types/events";

const CHART_COLORS = [
  "#3B82F6", "#10B981", "#F59E0B", "#8B5CF6",
  "#EC4899", "#06B6D4", "#F97316", "#84CC16",
];

export default function ScatterChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";

  // If hue provided, render multiple scatter sets
  if (hue) {
    const hueValues = Array.from(new Set(data.map((d) => String(d[hue]))));
    const scatterSets = hueValues.map((val) =>
      data
        .filter((d) => String(d[hue]) === val)
        .map((d) => ({ [xKey]: d[xKey], [yKey]: d[yKey] }))
    );

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: "#6B7280" }} name={xKey} />
              <YAxis dataKey={yKey} tick={{ fontSize: 11, fill: "#6B7280" }} name={yKey} />
              <ZAxis range={[36, 36]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "white",
                  borderRadius: 6,
                  border: "1px solid #E5E7EB",
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {hueValues.map((val, i) => (
                <Scatter
                  key={val}
                  name={val}
                  data={scatterSets[i]}
                  fill={CHART_COLORS[i % CHART_COLORS.length]}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  const scatterData = data.map((d) => ({ [xKey]: d[xKey], [yKey]: d[yKey] }));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: "#6B7280" }} name={xKey} />
            <YAxis dataKey={yKey} tick={{ fontSize: 11, fill: "#6B7280" }} name={yKey} />
            <ZAxis range={[36, 36]} />
            <Tooltip
              contentStyle={{
                backgroundColor: "white",
                borderRadius: 6,
                border: "1px solid #E5E7EB",
                fontSize: 12,
              }}
            />
            <Scatter data={scatterData} fill={CHART_COLORS[0]} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
