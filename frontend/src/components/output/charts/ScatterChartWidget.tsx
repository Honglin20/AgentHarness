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
import { PALETTE, AXIS_TICK, TOOLTIP_STYLE, LEGEND_STYLE, CHART_MARGIN, GRID_PROPS } from "./chartTheme";

export default function ScatterChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";

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
            <ScatterChart margin={CHART_MARGIN}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey={xKey} tick={AXIS_TICK} name={xKey} />
              <YAxis dataKey={yKey} tick={AXIS_TICK} name={yKey} />
              <ZAxis range={[36, 36]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Scatter
                  key={val}
                  name={val}
                  data={scatterSets[i]}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={0.8}
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
          <ScatterChart margin={CHART_MARGIN}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey={xKey} tick={AXIS_TICK} name={xKey} />
            <YAxis dataKey={yKey} tick={AXIS_TICK} name={yKey} />
            <ZAxis range={[36, 36]} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={scatterData} fill={PALETTE[0]} fillOpacity={0.8} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
