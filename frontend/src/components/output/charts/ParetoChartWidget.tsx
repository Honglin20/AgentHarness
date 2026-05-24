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

function findParetoFront(
  points: { x: number; y: number }[],
  direction: "max" | "min",
): Set<number> {
  const front = new Set<number>();
  for (let i = 0; i < points.length; i++) {
    let dominated = false;
    for (let j = 0; j < points.length; j++) {
      if (i === j) continue;
      const [ax, ay] = [points[i].x, points[i].y];
      const [bx, by] = [points[j].x, points[j].y];
      if (
        direction === "max" &&
        bx >= ax && by >= ay &&
        (bx > ax || by > ay)
      ) { dominated = true; break; }
      if (
        direction === "min" &&
        bx <= ax && by <= ay &&
        (bx < ax || by < ay)
      ) { dominated = true; break; }
    }
    if (!dominated) front.add(i);
  }
  return front;
}

export default function ParetoChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title, pareto_direction } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const direction = pareto_direction ?? "max";

  const points = data.map((d) => ({
    x: Number(d[xKey]),
    y: Number(d[yKey]),
  }));

  const frontIndices = findParetoFront(points, direction);
  const dominatedData = points
    .filter((_, i) => !frontIndices.has(i))
    .map((p) => ({ x: p.x, y: p.y }));
  const frontData = points
    .filter((_, i) => frontIndices.has(i))
    .map((p) => ({ x: p.x, y: p.y }));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={CHART_MARGIN}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey="x" tick={AXIS_TICK} name={xKey} />
            <YAxis dataKey="y" tick={AXIS_TICK} name={yKey} />
            <ZAxis range={[40, 200]} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            <Scatter name="Dominated" data={dominatedData} fill={NEUTRAL} fillOpacity={0.5} />
            <Scatter name="Pareto Front" data={frontData} fill={PALETTE[0]} fillOpacity={0.85} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const NEUTRAL = "#B0BEC5";
