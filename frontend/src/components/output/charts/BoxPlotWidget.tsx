"use client";

import React from "react";
import type { ChartPayload } from "@/types/events";

const CHART_COLORS = [
  "#3B82F6", "#10B981", "#F59E0B", "#8B5CF6",
  "#EC4899", "#06B6D4", "#F97316", "#84CC16",
];

interface BoxStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

function computeBoxStats(values: number[]): BoxStats {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const median = sorted[Math.floor(n / 2)];
  const q1 = sorted[Math.floor(n / 4)];
  const q3 = sorted[Math.floor((3 * n) / 4)];
  return { min: sorted[0], q1, median, q3, max: sorted[n - 1] };
}

export default function BoxPlotWidget({ chart }: { chart: ChartPayload }) {
  const { data, columns, title } = chart;

  // Group data by hue if provided, otherwise treat all as one group
  const hue = chart.hue;
  const yKey = chart.y ?? "y";

  let groups: { name: string; values: number[] }[];

  if (hue) {
    const hueMap = new Map<string, number[]>();
    data.forEach((d) => {
      const key = String(d[hue]);
      const val = Number(d[yKey]);
      if (!hueMap.has(key)) hueMap.set(key, []);
      hueMap.get(key)!.push(val);
    });
    groups = Array.from(hueMap.entries()).map(([name, values]) => ({ name, values }));
  } else {
    // Use all numeric columns (excluding x/hue) or just y
    groups = columns
      .filter((col) => col !== (chart.x ?? "x") && col !== hue)
      .map((col) => ({
        name: col,
        values: data.map((d) => Number(d[col])).filter((v) => !isNaN(v)),
      }))
      .filter((g) => g.values.length > 0);

    // Fallback: if no columns matched, use y key
    if (groups.length === 0) {
      groups = [
        {
          name: yKey,
          values: data.map((d) => Number(d[yKey])),
        },
      ];
    }
  }

  const stats = groups.map((g) => computeBoxStats(g.values));

  // Find global min/max for y axis
  const globalMin = Math.min(...stats.map((s) => s.min));
  const globalMax = Math.max(...stats.map((s) => s.max));
  const padding = (globalMax - globalMin) * 0.1 || 1;
  const yMin = globalMin - padding;
  const yMax = globalMax + padding;

  const svgWidth = Math.max(groups.length * 80 + 60, 200);
  const svgHeight = 250;
  const plotLeft = 50;
  const plotRight = svgWidth - 20;
  const plotTop = 20;
  const plotBottom = svgHeight - 40;
  const plotHeight = plotBottom - plotTop;

  function scaleY(val: number): number {
    return plotBottom - ((val - yMin) / (yMax - yMin)) * plotHeight;
  }

  const groupWidth = (plotRight - plotLeft) / groups.length;
  const boxWidth = Math.min(groupWidth * 0.6, 50);

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div className="aspect-[4/3] w-full overflow-auto">
        <svg width={svgWidth} height={svgHeight} className="block">
          {/* Y axis */}
          <line x1={plotLeft} y1={plotTop} x2={plotLeft} y2={plotBottom} stroke="#E5E7EB" />
          {/* Y axis ticks */}
          {[yMin, (yMin + yMax) / 2, yMax].map((val, i) => (
            <React.Fragment key={i}>
              <line
                x1={plotLeft - 4}
                y1={scaleY(val)}
                x2={plotLeft}
                y2={scaleY(val)}
                stroke="#6B7280"
              />
              <text
                x={plotLeft - 8}
                y={scaleY(val) + 3}
                textAnchor="end"
                fontSize={9}
                fill="#6B7280"
              >
                {val.toFixed(1)}
              </text>
              <line
                x1={plotLeft}
                y1={scaleY(val)}
                x2={plotRight}
                y2={scaleY(val)}
                stroke="#F3F4F6"
                strokeDasharray="3 3"
              />
            </React.Fragment>
          ))}

          {/* Box plots */}
          {stats.map((s, i) => {
            const cx = plotLeft + groupWidth * i + groupWidth / 2;
            const halfBox = boxWidth / 2;
            const color = CHART_COLORS[i % CHART_COLORS.length];

            return (
              <React.Fragment key={i}>
                {/* Whisker line (min to max) */}
                <line
                  x1={cx}
                  y1={scaleY(s.min)}
                  x2={cx}
                  y2={scaleY(s.max)}
                  stroke={color}
                  strokeWidth={1.5}
                />
                {/* Min whisker cap */}
                <line
                  x1={cx - halfBox * 0.4}
                  y1={scaleY(s.min)}
                  x2={cx + halfBox * 0.4}
                  y2={scaleY(s.min)}
                  stroke={color}
                  strokeWidth={1.5}
                />
                {/* Max whisker cap */}
                <line
                  x1={cx - halfBox * 0.4}
                  y1={scaleY(s.max)}
                  x2={cx + halfBox * 0.4}
                  y2={scaleY(s.max)}
                  stroke={color}
                  strokeWidth={1.5}
                />
                {/* Box (Q1 to Q3) */}
                <rect
                  x={cx - halfBox}
                  y={scaleY(s.q3)}
                  width={boxWidth}
                  height={scaleY(s.q1) - scaleY(s.q3)}
                  fill={color}
                  fillOpacity={0.25}
                  stroke={color}
                  strokeWidth={1.5}
                  rx={2}
                />
                {/* Median line */}
                <line
                  x1={cx - halfBox}
                  y1={scaleY(s.median)}
                  x2={cx + halfBox}
                  y2={scaleY(s.median)}
                  stroke={color}
                  strokeWidth={2}
                />
                {/* Group label */}
                <text
                  x={cx}
                  y={plotBottom + 16}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#6B7280"
                >
                  {groups[i].name.length > 8
                    ? groups[i].name.slice(0, 8) + "..."
                    : groups[i].name}
                </text>
              </React.Fragment>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
