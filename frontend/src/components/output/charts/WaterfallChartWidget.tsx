"use client";

import React, { useRef, useEffect, useState, useCallback, useMemo } from "react";
import type { ChartPayload } from "@/types/events";
import { PALETTE, getAxisTick, getTooltipStyle } from "./chartTheme";

interface WaterfallRow {
  agent: string;
  start_ms: number;
  duration_ms: number;
  kind: "llm" | "tool";
  label: string;
}

function toRows(data: Record<string, unknown>[]): WaterfallRow[] {
  return data.map((d) => ({
    agent: String(d.agent ?? ""),
    start_ms: Number(d.start_ms ?? 0),
    duration_ms: Number(d.duration_ms ?? 0),
    kind: d.kind === "tool" ? "tool" : "llm",
    label: String(d.label ?? ""),
  }));
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

const ROW_HEIGHT = 24;
const BAR_HEIGHT = 16;
const LABEL_WIDTH = 120;
const TOP_PADDING = 20;
const BOTTOM_PADDING = 28;
const RIGHT_PADDING = 16;
const BAR_RADIUS = 3;

const LLM_COLOR = PALETTE[0]; // steel blue
const TOOL_COLOR = PALETTE[1]; // warm amber

interface TooltipState {
  row: WaterfallRow;
  x: number;
  y: number;
}

export default function WaterfallChartWidget({ chart }: { chart: ChartPayload }) {
  const { data, title } = chart;
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(400);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

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

  const handleMouseEnter = useCallback(
    (row: WaterfallRow, e: React.MouseEvent<SVGRectElement>) => {
      const svg = (e.target as SVGElement).closest("svg");
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      setTooltip({ row, x: e.clientX - rect.left, y: e.clientY - rect.top });
    },
    [],
  );

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  const rows = useMemo(() => {
    if (!data || data.length === 0) return [] as WaterfallRow[];
    return [...toRows(data)].sort((a, b) => a.start_ms - b.start_ms);
  }, [data]);

  if (rows.length === 0) {
    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="py-6 text-center text-xs text-muted-foreground">
          No timeline data available
        </div>
      </div>
    );
  }

  const maxEnd = Math.max(...rows.map((r) => r.start_ms + r.duration_ms), 1);
  const chartWidth = Math.max(containerWidth - LABEL_WIDTH - RIGHT_PADDING, 80);
  const svgHeight = TOP_PADDING + rows.length * ROW_HEIGHT + BOTTOM_PADDING;

  const xScale = (ms: number) => (ms / maxEnd) * chartWidth;

  const tickCount = Math.min(6, Math.max(2, Math.floor(chartWidth / 80)));
  const ticks: number[] = [];
  for (let i = 0; i <= tickCount; i++) ticks.push((maxEnd * i) / tickCount);

  const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  return (
    <div className="flex flex-col">
      <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>

      {/* Legend */}
      <div className="mb-2 flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: LLM_COLOR }}
          />
          LLM
        </span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: TOOL_COLOR }}
          />
          Tool
        </span>
      </div>

      <div ref={containerRef} className="w-full">
        <svg
          viewBox={`0 0 ${LABEL_WIDTH + chartWidth + RIGHT_PADDING} ${svgHeight}`}
          width="100%"
          className="block"
        >
          {/* Row labels (y-axis) — one per span */}
          {rows.map((row, i) => {
            const cy = TOP_PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2;
            return (
              <text
                key={`label-${i}`}
                x={LABEL_WIDTH - 6}
                y={cy + 3}
                textAnchor="end"
                fontSize={axisTick.fontSize}
                fill={axisTick.fill}
              >
                {truncate(row.label, 16)}
              </text>
            );
          })}

          {/* Row separators */}
          {rows.map((_, i) => {
            const ly = TOP_PADDING + (i + 1) * ROW_HEIGHT;
            return (
              <line
                key={`sep-${i}`}
                x1={LABEL_WIDTH}
                y1={ly}
                x2={LABEL_WIDTH + chartWidth}
                y2={ly}
                stroke="currentColor"
                strokeOpacity={0.06}
              />
            );
          })}

          {/* X-axis ticks */}
          {ticks.map((t, ti) => {
            const tx = LABEL_WIDTH + xScale(t);
            return (
              <g key={`tick-${ti}`}>
                <text
                  x={tx}
                  y={svgHeight - 6}
                  textAnchor="middle"
                  fontSize={axisTick.fontSize}
                  fill={axisTick.fill}
                >
                  {formatMs(t)}
                </text>
                <line
                  x1={tx}
                  y1={TOP_PADDING}
                  x2={tx}
                  y2={TOP_PADDING + rows.length * ROW_HEIGHT}
                  stroke="currentColor"
                  strokeOpacity={0.04}
                  strokeDasharray="3 3"
                />
              </g>
            );
          })}

          {/* Bars */}
          {rows.map((row, i) => {
            const barY = TOP_PADDING + i * ROW_HEIGHT + (ROW_HEIGHT - BAR_HEIGHT) / 2;
            const barX = LABEL_WIDTH + xScale(row.start_ms);
            const barW = Math.max(xScale(row.duration_ms), 2);
            const color = row.kind === "tool" ? TOOL_COLOR : LLM_COLOR;

            return (
              <rect
                key={`bar-${i}`}
                x={barX}
                y={barY}
                width={barW}
                height={BAR_HEIGHT}
                fill={color}
                fillOpacity={0.8}
                rx={BAR_RADIUS}
                onMouseEnter={(e) => handleMouseEnter(row, e)}
                onMouseLeave={handleMouseLeave}
                style={{ cursor: "pointer" }}
              >
                <title>{`${row.label} — ${formatMs(row.duration_ms)}`}</title>
              </rect>
            );
          })}

          {/* Tooltip */}
          {tooltip && (
            <foreignObject
              x={Math.min(tooltip.x + 12, LABEL_WIDTH + chartWidth - 180)}
              y={Math.max(tooltip.y - 56, 0)}
              width={180}
              height={70}
              style={{ pointerEvents: "none" }}
            >
              <div
                style={{
                  ...tooltipStyle,
                  fontSize: 11,
                  lineHeight: 1.4,
                  pointerEvents: "none",
                }}
              >
                <div style={{ fontWeight: 600 }}>{tooltip.row.label}</div>
                <div>kind: {tooltip.row.kind}</div>
                <div>
                  {formatMs(tooltip.row.start_ms)} → {formatMs(tooltip.row.start_ms + tooltip.row.duration_ms)}
                </div>
                <div>duration: {formatMs(tooltip.row.duration_ms)}</div>
              </div>
            </foreignObject>
          )}
        </svg>
      </div>
    </div>
  );
}
