"use client";

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { ChartPayload, SeriesConfig } from "@/types/events";
import {
  PALETTE,
  LEGEND_STYLE,
  CHART_MARGIN,
  getGridProps,
  getAxisTick,
  getTooltipStyle,
} from "./chartTheme";
import { computeNiceTicks, formatTick, extractNumericValues } from "./axisUtils";

const DEFAULT_AREA_FILL = 0.2;
const DEFAULT_STROKE_WIDTH = 1.5;

export default function DistOverlayChartWidget({
  chart,
}: {
  chart: ChartPayload;
}) {
  const { data, x, title, series: rawSeries } = chart;
  const xKey = x ?? "x";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const series: SeriesConfig[] = rawSeries ?? [];

  // Split series by axis
  const leftSeries = series.filter((s) => (s.axis ?? "left") === "left");
  const rightSeries = series.filter((s) => s.axis === "right");

  // Compute axis domains
  const leftValues = leftSeries.flatMap((s) =>
    extractNumericValues(data, s.key)
  );
  const rightValues = rightSeries.flatMap((s) =>
    extractNumericValues(data, s.key)
  );

  const leftYConfig = leftValues.length
    ? computeNiceTicks(leftValues)
    : { ticks: [0], domain: [0, 1] as [number, number] };
  const rightYConfig = rightValues.length
    ? computeNiceTicks(rightValues)
    : { ticks: [0], domain: [0, 1] as [number, number] };

  const hasRightAxis = rightSeries.length > 0;

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">
        {title}
      </h4>
      <div className="aspect-[4/3] w-full max-h-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} tick={axisTick} />
            <YAxis
              yAxisId="left"
              tick={axisTick}
              domain={leftYConfig.domain}
              ticks={leftYConfig.ticks}
              tickFormatter={formatTick}
            />
            {hasRightAxis && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={axisTick}
                domain={rightYConfig.domain}
                ticks={rightYConfig.ticks}
                tickFormatter={formatTick}
              />
            )}
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {series.map((s, i) => {
              const color = s.color ?? PALETTE[i % PALETTE.length];
              const axisId = (s.axis ?? "left") === "left" ? "left" : "right";
              const interp = s.step ? "stepAfter" : "monotone";
              const displayName = s.label ?? s.key;

              if (s.type === "line") {
                return (
                  <Line
                    key={s.key}
                    yAxisId={axisId}
                    dataKey={s.key}
                    name={displayName}
                    stroke={color}
                    strokeWidth={s.strokeWidth ?? DEFAULT_STROKE_WIDTH}
                    strokeDasharray={s.dash || undefined}
                    dot={false}
                    type={interp as "monotone" | "stepAfter"}
                  />
                );
              }

              // area (default)
              return (
                <Area
                  key={s.key}
                  yAxisId={axisId}
                  dataKey={s.key}
                  name={displayName}
                  stroke={color}
                  fill={color}
                  fillOpacity={s.fillOpacity ?? DEFAULT_AREA_FILL}
                  strokeWidth={s.strokeWidth ?? DEFAULT_STROKE_WIDTH}
                  type={interp as "monotone" | "stepAfter"}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
