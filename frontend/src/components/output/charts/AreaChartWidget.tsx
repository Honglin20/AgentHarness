"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, AXIS_TICK, TOOLTIP_STYLE, LEGEND_STYLE, CHART_MARGIN, GRID_PROPS } from "./chartTheme";

export default function AreaChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";

  if (hue) {
    const hueValues = Array.from(new Set(data.map((d) => String(d[hue]))));
    const xMap = new Map<string, Record<string, unknown>>();
    data.forEach((d) => {
      const xv = String(d[xKey]);
      if (!xMap.has(xv)) xMap.set(xv, { [xKey]: d[xKey] });
      const row = xMap.get(xv)!;
      row[String(d[hue])] = d[yKey];
    });
    const pivotedData = Array.from(xMap.values());

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={pivotedData} margin={CHART_MARGIN}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey={xKey} tick={AXIS_TICK} />
              <YAxis tick={AXIS_TICK} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Area
                  key={val}
                  dataKey={val}
                  stroke={PALETTE[i % PALETTE.length]}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                  type="monotone"
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey={xKey} tick={AXIS_TICK} />
            <YAxis tick={AXIS_TICK} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Area
              dataKey={yKey}
              stroke={PALETTE[0]}
              fill={PALETTE[0]}
              fillOpacity={0.15}
              strokeWidth={2}
              type="monotone"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
