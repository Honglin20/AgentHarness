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
        bx >= ax &&
        by >= ay &&
        (bx > ax || by > ay)
      ) {
        dominated = true;
        break;
      }
      if (
        direction === "min" &&
        bx <= ax &&
        by <= ay &&
        (bx < ax || by < ay)
      ) {
        dominated = true;
        break;
      }
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
          <ScatterChart margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="x" tick={{ fontSize: 11, fill: "#6B7280" }} name={xKey} />
            <YAxis dataKey="y" tick={{ fontSize: 11, fill: "#6B7280" }} name={yKey} />
            <ZAxis range={[36, 200]} />
            <Tooltip
              contentStyle={{
                backgroundColor: "white",
                borderRadius: 6,
                border: "1px solid #E5E7EB",
                fontSize: 12,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Scatter
              name="Dominated Points"
              data={dominatedData}
              fill="#9CA3AF"
              fillOpacity={0.6}
            />
            <Scatter
              name="Pareto Front"
              data={frontData}
              fill="#3B82F6"
              fillOpacity={0.8}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
