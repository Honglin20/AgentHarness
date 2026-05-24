"use client";

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, TOOLTIP_STYLE, LEGEND_STYLE } from "./chartTheme";

export default function RadarChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "dimension";
  const yKey = y ?? "value";

  if (hue) {
    const hueValues = Array.from(new Set(data.map((d) => String(d[hue]))));
    const dimensions = Array.from(new Set(data.map((d) => String(d[xKey]))));

    // Pivot: one row per dimension, one column per hue value
    const pivoted = dimensions.map((dim) => {
      const row: Record<string, unknown> = { [xKey]: dim };
      hueValues.forEach((hv) => {
        const match = data.find(
          (d) => String(d[xKey]) === dim && String(d[hue]) === hv,
        );
        row[hv] = match ? Number(match[yKey]) : 0;
      });
      return row;
    });

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-square w-full max-w-[400px] mx-auto">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={pivoted} cx="50%" cy="50%" outerRadius="75%">
              <PolarGrid stroke="#CBD5E1" />
              <PolarAngleAxis dataKey={xKey} tick={{ fontSize: 10, fill: "#64748B" }} />
              <PolarRadiusAxis tick={{ fontSize: 9, fill: "#94A3B8" }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Radar
                  key={val}
                  name={val}
                  dataKey={val}
                  stroke={PALETTE[i % PALETTE.length]}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                />
              ))}
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-square w-full max-w-[400px] mx-auto">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
            <PolarGrid stroke="#CBD5E1" />
            <PolarAngleAxis dataKey={xKey} tick={{ fontSize: 10, fill: "#64748B" }} />
            <PolarRadiusAxis tick={{ fontSize: 9, fill: "#94A3B8" }} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Radar
              dataKey={yKey}
              stroke={PALETTE[0]}
              fill={PALETTE[0]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
