"use client";

import React, { useRef, useEffect, useState } from "react";
import type { ChartPayload } from "@/types/events";
import { HEATMAP_LIGHT, HEATMAP_DARK, getAxisTick } from "./chartTheme";

function hexToRgb(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
}

export default function HeatmapWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const axisTick = getAxisTick();

  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(300);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

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

  const [lightR, lightG, lightB] = hexToRgb(HEATMAP_LIGHT);
  const [darkR, darkG, darkB] = hexToRgb(HEATMAP_DARK);

  function getColor(val: number): string {
    const t = (val - minVal) / range;
    const r = Math.round(lightR + (darkR - lightR) * t);
    const g = Math.round(lightG + (darkG - lightG) * t);
    const b = Math.round(lightB + (darkB - lightB) * t);
    return `rgb(${r},${g},${b})`;
  }

  const labelWidth = 60;
  const labelHeight = 40;
  const availableWidth = containerWidth - labelWidth - 20;
  const cellSize = Math.max(16, Math.floor(availableWidth / xLabels.length));

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div ref={containerRef} className="w-full">
        <svg
          viewBox={`0 0 ${labelWidth + xLabels.length * cellSize + 20} ${labelHeight + yLabels.length * cellSize + 20}`}
          width="100%"
          className="block"
        >
          {xLabels.map((xl, i) => (
            <text
              key={xl}
              x={labelWidth + i * cellSize + cellSize / 2}
              y={labelHeight - 6}
              textAnchor="middle"
              fontSize={axisTick.fontSize}
              fill={axisTick.fill}
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
              fontSize={axisTick.fontSize}
              fill={axisTick.fill}
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
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span>{minVal.toFixed(1)}</span>
          <div
            className="h-2 flex-1 rounded"
            style={{
              background: `linear-gradient(to right, ${HEATMAP_LIGHT}, ${HEATMAP_DARK})`,
            }}
          />
          <span>{maxVal.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}
