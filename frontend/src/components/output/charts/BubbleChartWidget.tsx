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

export default function BubbleChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, size, hue, title } = chart as ChartPayload & { size?: string };
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const sizeKey = size ?? "size";

  if (hue) {
    const hueValues = Array.from(new Set(data.map((d) => String(d[hue]))));
    const bubbleSets = hueValues.map((val) =>
      data
        .filter((d) => String(d[hue]) === val)
        .map((d) => ({
          [xKey]: Number(d[xKey]),
          [yKey]: Number(d[yKey]),
          z: Number(d[sizeKey] ?? 1),
        }))
    );

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={CHART_MARGIN}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey={xKey} tick={AXIS_TICK} name={xKey} type="number" />
              <YAxis dataKey={yKey} tick={AXIS_TICK} name={yKey} type="number" />
              <ZAxis dataKey="z" range={[50, 400]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Scatter
                  key={val}
                  name={val}
                  data={bubbleSets[i]}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={0.65}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  const bubbleData = data.map((d) => ({
    [xKey]: Number(d[xKey]),
    [yKey]: Number(d[yKey]),
    z: Number(d[sizeKey] ?? 1),
  }));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={CHART_MARGIN}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey={xKey} tick={AXIS_TICK} name={xKey} type="number" />
            <YAxis dataKey={yKey} tick={AXIS_TICK} name={yKey} type="number" />
            <ZAxis dataKey="z" range={[50, 400]} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={bubbleData} fill={PALETTE[0]} fillOpacity={0.65} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
