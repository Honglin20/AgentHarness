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
import { PALETTE, LEGEND_STYLE, BOX_FILL_OPACITY, BOX_STROKE_WIDTH, getGridStroke, getAxisTick, getTooltipStyle } from "./chartTheme";

export default function RadarChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "dimension";
  const yKey = y ?? "value";
  const gridStroke = getGridStroke();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

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
          <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
            <RadarChart data={pivoted} cx="50%" cy="50%" outerRadius="75%">
              <PolarGrid stroke={gridStroke} />
              <PolarAngleAxis dataKey={xKey} tick={{ fontSize: 10, fill: axisTick.fill }} />
              <PolarRadiusAxis tick={{ fontSize: 9, fill: axisTick.fill }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Radar
                  key={val}
                  name={val}
                  dataKey={val}
                  stroke={PALETTE[i % PALETTE.length]}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={BOX_FILL_OPACITY}
                  strokeWidth={BOX_STROKE_WIDTH}
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
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
            <PolarGrid stroke={gridStroke} />
            <PolarAngleAxis dataKey={xKey} tick={{ fontSize: 10, fill: axisTick.fill }} />
            <PolarRadiusAxis tick={{ fontSize: 9, fill: axisTick.fill }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Radar
              dataKey={yKey}
              stroke={PALETTE[0]}
              fill={PALETTE[0]}
              fillOpacity={BOX_FILL_OPACITY}
              strokeWidth={BOX_STROKE_WIDTH}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
