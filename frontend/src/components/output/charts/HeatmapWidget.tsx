"use client";

import React from "react";
import type { ChartPayload } from "@/types/events";

export default function HeatmapWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";

  // Extract unique x and y labels
  const xLabels = Array.from(new Set(data.map((d) => String(d[xKey]))));
  const yLabels = Array.from(new Set(data.map((d) => String(d[yKey]))));

  // Find min/max value for color scaling
  const values = data.map((d) => Number(d.value ?? d.v ?? 0));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  // Build lookup map: "x,y" -> value
  const valueMap = new Map<string, number>();
  data.forEach((d) => {
    const key = `${String(d[xKey])},${String(d[yKey])}`;
    valueMap.set(key, Number(d.value ?? d.v ?? 0));
  });

  // Color interpolation: blue (#3B82F6) for low, red (#EF4444) for high
  function getColor(val: number): string {
    const t = (val - minVal) / range;
    const r = Math.round(59 + (239 - 59) * t);
    const g = Math.round(130 + (68 - 130) * t);
    const b = Math.round(246 + (68 - 246) * t);
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
          {/* Column labels (x) */}
          {xLabels.map((xl, i) => (
            <text
              key={xl}
              x={labelWidth + i * cellSize + cellSize / 2}
              y={labelHeight - 6}
              textAnchor="middle"
              fontSize={9}
              fill="#6B7280"
            >
              {xl.length > 6 ? xl.slice(0, 6) + "..." : xl}
            </text>
          ))}
          {/* Row labels (y) */}
          {yLabels.map((yl, i) => (
            <text
              key={yl}
              x={labelWidth - 4}
              y={labelHeight + i * cellSize + cellSize / 2 + 3}
              textAnchor="end"
              fontSize={9}
              fill="#6B7280"
            >
              {yl.length > 8 ? yl.slice(0, 8) + "..." : yl}
            </text>
          ))}
          {/* Cells */}
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
                  rx={2}
                >
                  <title>{`${xl}, ${yl}: ${val}`}</title>
                </rect>
              );
            }),
          )}
        </svg>
        {/* Color legend */}
        <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>{minVal.toFixed(1)}</span>
          <div
            className="h-2 flex-1 rounded"
            style={{
              background: "linear-gradient(to right, #3B82F6, #EF4444)",
            }}
          />
          <span>{maxVal.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}
