"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, LEGEND_STYLE, CHART_MARGIN, getGridProps, getAxisTick, getTooltipStyle } from "./chartTheme";
import { computeNiceTicks, formatTick, extractNumericValues } from "./axisUtils";

function EndLabel(props: any) {
  const { x, y, index, dataLength, value, color } = props;
  if (index !== dataLength - 1 || value == null || isNaN(value)) return null;
  return (
    <text x={x + 6} y={y + 4} fontSize={10} fill={color} fontWeight={500}>
      {typeof value === "number" ? value.toFixed(2) : value}
    </text>
  );
}

export default function LineChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, hue, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const allYValues = extractNumericValues(data, yKey);
  const yConfig = computeNiceTicks(allYValues);

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
    const pivotedYConfig = computeNiceTicks(pivotedYValues);

    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="aspect-[4/3] w-full">
          <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
            <LineChart data={pivotedData} margin={{ ...CHART_MARGIN, right: 60 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey={xKey} tick={axisTick} />
              <YAxis
                tick={axisTick}
                domain={pivotedYConfig.domain}
                ticks={pivotedYConfig.ticks}
                tickFormatter={formatTick}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              {hueValues.map((val, i) => {
                const color = PALETTE[i % PALETTE.length];
                return (
                  <Line
                    key={val}
                    dataKey={val}
                    stroke={color}
                    strokeWidth={2}
                    dot={{ r: 3, fill: color, strokeWidth: 0 }}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff", fill: color }}
                    label={<EndLabel color={color} dataLength={pivotedData.length} />}
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <LineChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} tick={axisTick} />
            <YAxis
              tick={axisTick}
              domain={yConfig.domain}
              ticks={yConfig.ticks}
              tickFormatter={formatTick}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Line
              dataKey={yKey}
              stroke={PALETTE[0]}
              strokeWidth={2}
              dot={{ r: 3, fill: PALETTE[0], strokeWidth: 0 }}
              activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff", fill: PALETTE[0] }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
