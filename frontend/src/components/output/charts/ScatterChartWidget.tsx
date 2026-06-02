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
import { PALETTE, LEGEND_STYLE, CHART_MARGIN, BOX_FILL_OPACITY, getGridProps, getAxisTick, getTooltipStyle } from "./chartTheme";
import { computeNiceTicks, formatTick, extractNumericValues } from "./axisUtils";

export default function ScatterChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const allXValues = extractNumericValues(data, xKey);
  const allYValues = extractNumericValues(data, yKey);
  const xConfig = computeNiceTicks(allXValues);
  const yConfig = computeNiceTicks(allYValues);

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
          <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
            <ScatterChart margin={CHART_MARGIN}>
              <CartesianGrid {...gridProps} />
              <XAxis
                dataKey={xKey}
                tick={axisTick}
                name={xKey}
                type="number"
                domain={xConfig.domain}
                ticks={xConfig.ticks}
                tickFormatter={formatTick}
              />
              <YAxis
                dataKey={yKey}
                tick={axisTick}
                name={yKey}
                type="number"
                domain={yConfig.domain}
                ticks={yConfig.ticks}
                tickFormatter={formatTick}
              />
              <ZAxis range={[36, 36]} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Scatter
                  key={val}
                  name={val}
                  data={scatterSets[i]}
                  fill="none"
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={1.5}
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
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <ScatterChart margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey={xKey}
              tick={axisTick}
              name={xKey}
              type="number"
              domain={xConfig.domain}
              ticks={xConfig.ticks}
              tickFormatter={formatTick}
            />
            <YAxis
              dataKey={yKey}
              tick={axisTick}
              name={yKey}
              type="number"
              domain={yConfig.domain}
              ticks={yConfig.ticks}
              tickFormatter={formatTick}
            />
            <ZAxis range={[36, 36]} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
            <Scatter
              data={scatterData}
              fill="none"
              stroke={PALETTE[0]}
              strokeWidth={1.5}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
