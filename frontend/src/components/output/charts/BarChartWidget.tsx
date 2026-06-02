"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, LEGEND_STYLE, CHART_MARGIN, BOX_FILL_OPACITY, BOX_STROKE_WIDTH, BOX_RADIUS, getGridProps, getAxisTick, getTooltipStyle } from "./chartTheme";
import { computeNiceTicks, formatTick, extractNumericValues } from "./axisUtils";

export default function BarChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

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

    const pivotedYValues = hueValues.flatMap((hv) =>
      extractNumericValues(pivotedData, hv)
    );
    const yConfig = computeNiceTicks(pivotedYValues);

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
            <BarChart data={pivotedData} margin={CHART_MARGIN}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey={xKey} tick={axisTick} />
              <YAxis
                tick={axisTick}
                domain={yConfig.domain}
                ticks={yConfig.ticks}
                tickFormatter={formatTick}
              />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => (
                <Bar
                  key={val}
                  dataKey={val}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={BOX_FILL_OPACITY}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={BOX_STROKE_WIDTH}
                  radius={[BOX_RADIUS, BOX_RADIUS, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  // Multi-column path: if chart.columns has more than x+y, render one Bar per column
  const extraColumns = (chart.columns ?? []).filter((col) => col !== xKey && col !== yKey);

  if (extraColumns.length > 0) {
    const allYKeys = [yKey, ...extraColumns];
    const allYValues = allYKeys.flatMap((key) => extractNumericValues(data, key));
    const yConfig = computeNiceTicks(allYValues);

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
            <BarChart data={data} margin={CHART_MARGIN}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey={xKey} tick={axisTick} />
              <YAxis
                tick={axisTick}
                domain={yConfig.domain}
                ticks={yConfig.ticks}
                tickFormatter={formatTick}
              />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {allYKeys.map((key, i) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={PALETTE[i % PALETTE.length]}
                  fillOpacity={BOX_FILL_OPACITY}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={BOX_STROKE_WIDTH}
                  radius={[BOX_RADIUS, BOX_RADIUS, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  const allYValues = extractNumericValues(data, yKey);
  const yConfig = computeNiceTicks(allYValues);

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <BarChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} tick={axisTick} />
            <YAxis
              tick={axisTick}
              domain={yConfig.domain}
              ticks={yConfig.ticks}
              tickFormatter={formatTick}
            />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
            <Bar
              dataKey={yKey}
              fill={PALETTE[0]}
              fillOpacity={BOX_FILL_OPACITY}
              stroke={PALETTE[0]}
              strokeWidth={BOX_STROKE_WIDTH}
              radius={[BOX_RADIUS, BOX_RADIUS, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
