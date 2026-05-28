"use client";

import {
  Scatter,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  ZAxis,
  ComposedChart,
} from "recharts";
import type { ChartPayload } from "@/types/events";
import { PALETTE, NEUTRAL, LEGEND_STYLE, CHART_MARGIN, getGridProps, getAxisTick, getTooltipStyle } from "./chartTheme";

function findParetoFront(
  points: { x: number; y: number }[],
  xDir: "max" | "min",
  yDir: "max" | "min",
): Set<number> {
  const front = new Set<number>();
  for (let i = 0; i < points.length; i++) {
    let dominated = false;
    for (let j = 0; j < points.length; j++) {
      if (i === j) continue;
      const [ax, ay] = [points[i].x, points[i].y];
      const [bx, by] = [points[j].x, points[j].y];

      const xBetter = xDir === "max" ? bx >= ax : bx <= ax;
      const yBetter = yDir === "max" ? by >= ay : by <= ay;
      const xStrict = xDir === "max" ? bx > ax : bx < ax;
      const yStrict = yDir === "max" ? by > ay : by < ay;

      if (xBetter && yBetter && (xStrict || yStrict)) {
        dominated = true;
        break;
      }
    }
    if (!dominated) front.add(i);
  }
  return front;
}

export default function ParetoChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const xDir = (chart as any).pareto_x_direction ?? chart.pareto_direction ?? "max";
  const yDir = (chart as any).pareto_y_direction ?? chart.pareto_direction ?? "max";
  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const points = data.map((d) => ({
    x: Number(d[xKey]),
    y: Number(d[yKey]),
  }));

  const frontIndices = findParetoFront(points, xDir, yDir);
  const dominatedData = points
    .filter((_, i) => !frontIndices.has(i))
    .map((p) => ({ x: p.x, y: p.y }));
  const frontData = points
    .filter((_, i) => frontIndices.has(i))
    .map((p) => ({ x: p.x, y: p.y }));

  const sortedFront = [...frontData].sort((a, b) => a.x - b.x);

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%" minHeight={200} minWidth={300}>
          <ComposedChart margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="x" tick={axisTick} name={xKey} type="number" />
            <YAxis dataKey="y" tick={axisTick} name={yKey} type="number" />
            <ZAxis range={[40, 200]} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Scatter name="Dominated" data={dominatedData} fill={NEUTRAL} fillOpacity={0.5} />
            <Scatter name="Pareto Front" data={frontData} fill={PALETTE[0]} fillOpacity={0.85} />
            {sortedFront.length > 1 && (
              <Line
                name="Front Line"
                data={sortedFront}
                dataKey="y"
                stroke={PALETTE[0]}
                strokeWidth={2}
                strokeDasharray="6 3"
                dot={false}
                type="linear"
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
