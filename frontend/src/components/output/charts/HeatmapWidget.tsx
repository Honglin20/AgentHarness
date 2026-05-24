"use client";

import React from "react";
import type { ChartPayload } from "@/types/events";

export default function HeatmapWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";

  const xLabels = Array.from(new Set(data.map((d) => String(d[xKey]))));
  const yLabels = Array.from(new Set(data.map((d) => String(d[yKey]))));

  const values = data.map((d) => Number(d.value ?? d.v ?? 0));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const valueMap = new Map<string, number>();
  data.forEach((d) => {
    const key = `${String(d[xKey])},${String(d[yKey])}`;
    valueMap.set(key, Number(d.value ?? d.v ?? 0));
  });

  // Professional sequential palette: pale steel → deep indigo
  function getColor(val: number): string {
    const t = (val - minVal) / range;
    const r = Math.round(237 + (67 - 237) * t);
    const g = Math.round(242 + (56 - 242) * t);
    const b = Math.round(251 + (120 - 251) * t);
    return `rgb(${r},${g},${b})`;
  }

  const cellSize = 28;
  const labelWidth = 60;
  const labelHeight = 40;
  const svgWidth = labelWidth + xLabels.length * cellSize + 20;
  const svgHeight = labelHeight + yLabels.length * cellSize + 20;

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full overflow-auto">
        <svg width={svgWidth} height={svgHeight} className="block">
          {xLabels.map((xl, i) => (
            <text
              key={xl}
              x={labelWidth + i * cellSize + cellSize / 2}
              y={labelHeight - 6}
              textAnchor="middle"
              fontSize={9}
              fill="#64748B"
            >
              {xl.length > 6 ? xl.slice(0, 6) + "..." : xl}
            </text>
          ))}
          {yLabels.map((yl, i) => (
            <text
              key={yl}
              x={labelWidth - 4}
              y={labelHeight + i * cellSize + cellSize / 2 + 3}
              textAnchor="end"
              fontSize={9}
              fill="#64748B"
            >
              {yl.length > 8 ? yl.slice(0, 8) + "..." : yl}
            </text>
          ))}
          {yLabels.map((yl, yi) =>
            xLabels.map((xl, xi) => {
              const val = valueMap.get(`${xl},${yl}`);
              if (val === undefined) return null;
              return (
                <rect
                  key={`${xl}-${yl}`}
                  x={labelWidth + xi * cellSize}
                  y={labelHeight + yi * cellSize}
                  width={cellSize - 1}
                  height={cellSize - 1}
                  fill={getColor(val)}
                  rx={3}
                >
                  <title>{`${xl}, ${yl}: ${val}`}</title>
                </rect>
              );
            }),
          )}
        </svg>
        <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>{minVal.toFixed(1)}</span>
          <div
            className="h-2 flex-1 rounded"
            style={{
              background: "linear-gradient(to right, #EDF2FB, #4338CA)",
            }}
          />
          <span>{maxVal.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}
