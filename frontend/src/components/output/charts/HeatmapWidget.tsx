"use client";

import React, { useRef, useEffect, useState, useMemo } from "react";
import type { ChartPayload } from "@/types/events";
import { HEATMAP_LIGHT, HEATMAP_DARK, getAxisTick } from "./chartTheme";

function hexToRgb(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
}

/** Estimate pixel width of a text string at given font size */
function textWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.6;
}

export default function HeatmapWidget({ chart }: { chart: ChartPayload }) {
  const { data, x, y, title } = chart;
  const xKey = x ?? "x";
  const yKey = y ?? "y";
  const axisTick = getAxisTick();
  const fontSize = axisTick.fontSize ?? 10;

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

  const xLabels = useMemo(() => Array.from(new Set(data.map((d) => String(d[xKey])))), [data, xKey]);
  const yLabels = useMemo(() => Array.from(new Set(data.map((d) => String(d[yKey])))), [data, yKey]);

  const values = data.map((d) => Number(d.value ?? d.v ?? 0));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const valueMap = useMemo(() => {
    const m = new Map<string, number>();
    data.forEach((d) => {
      const key = `${String(d[xKey])},${String(d[yKey])}`;
      m.set(key, Number(d.value ?? d.v ?? 0));
    });
    return m;
  }, [data, xKey, yKey]);

  const [lightR, lightG, lightB] = hexToRgb(HEATMAP_LIGHT);
  const [darkR, darkG, darkB] = hexToRgb(HEATMAP_DARK);

  function getColor(val: number): string {
    const t = (val - minVal) / range;
    const r = Math.round(lightR + (darkR - lightR) * t);
    const g = Math.round(lightG + (darkG - lightG) * t);
    const b = Math.round(lightB + (darkB - lightB) * t);
    return `rgb(${r},${g},${b})`;
  }

  // Dynamic label dimensions based on actual label lengths
  const maxYLableLen = yLabels.reduce((max, l) => Math.max(max, l.length), 0);
  const labelWidth = Math.max(50, Math.min(120, maxYLableLen * fontSize * 0.65 + 8));

  // Rotate x labels when many or long
  const shouldRotate = xLabels.length > 6 || xLabels.some((l) => l.length > 6);
  const labelHeight = shouldRotate ? 60 : 30;

  const rightPad = 16;
  const availableWidth = containerWidth - labelWidth - rightPad;
  const cellSize = Math.max(20, Math.floor(availableWidth / xLabels.length));

  // Max chars that fit in a cell before truncating
  const maxCharsPerCell = Math.max(4, Math.floor(cellSize / (fontSize * 0.6)));

  // Truncate helper — preserves tooltip via <title>
  const truncate = (s: string, max: number) =>
    s.length > max ? s.slice(0, max - 1) + "…" : s;

  const svgWidth = labelWidth + xLabels.length * cellSize + rightPad;
  const svgHeight = labelHeight + yLabels.length * cellSize + 10;

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
      <div ref={containerRef} className="w-full">
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          width="100%"
          className="block"
        >
          {/* X-axis labels */}
          {xLabels.map((xl, i) => {
            const cx = labelWidth + i * cellSize + cellSize / 2;
            if (shouldRotate) {
              return (
                <text
                  key={xl}
                  x={cx}
                  y={labelHeight - 4}
                  textAnchor="end"
                  transform={`rotate(-45, ${cx}, ${labelHeight - 4})`}
                  fontSize={fontSize}
                  fill={axisTick.fill}
                >
                  <title>{xl}</title>
                  {truncate(xl, maxCharsPerCell + 4)}
                </text>
              );
            }
            return (
              <text
                key={xl}
                x={cx}
                y={labelHeight - 6}
                textAnchor="middle"
                fontSize={fontSize}
                fill={axisTick.fill}
              >
                <title>{xl}</title>
                {truncate(xl, maxCharsPerCell)}
              </text>
            );
          })}

          {/* Y-axis labels */}
          {yLabels.map((yl, i) => {
            const maxLen = Math.floor((labelWidth - 8) / (fontSize * 0.6));
            return (
              <text
                key={yl}
                x={labelWidth - 4}
                y={labelHeight + i * cellSize + cellSize / 2 + 3}
                textAnchor="end"
                fontSize={fontSize}
                fill={axisTick.fill}
              >
                <title>{yl}</title>
                {truncate(yl, maxLen)}
              </text>
            );
          })}

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
