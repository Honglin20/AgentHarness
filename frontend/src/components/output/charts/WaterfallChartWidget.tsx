"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
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
  return `${(ms / 1000).toFixed(1)}s`;
}

const ROW_HEIGHT = 28;
const BAR_HEIGHT = 18;
const LABEL_WIDTH = 80;
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
      const pt = svg.createSVGPoint();
      pt.x = e.clientX - rect.left;
      pt.y = e.clientY - rect.top;
      setTooltip({ row, x: pt.x, y: pt.y });
    },
    [],
  );

  const handleMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col">
        <h4 className="mb-2 text-xs font-medium text-app-text-primary">{title}</h4>
        <div className="py-6 text-center text-xs text-muted-foreground">
          No timeline data available
        </div>
      </div>
    );
  }

  const rows = toRows(data);

  // Build unique agent list preserving insertion order
  const agentSet = new Set<string>();
  const agents: string[] = [];
  for (const r of rows) {
    if (!agentSet.has(r.agent)) {
      agentSet.add(r.agent);
      agents.push(r.agent);
    }
  }

  const maxEnd = Math.max(...rows.map((r) => r.start_ms + r.duration_ms), 1);
  const chartWidth = containerWidth - LABEL_WIDTH - RIGHT_PADDING;
  const svgHeight = TOP_PADDING + agents.length * ROW_HEIGHT + BOTTOM_PADDING;

  function xScale(ms: number): number {
    return (ms / maxEnd) * chartWidth;
  }

  // Tick marks on x-axis
  const tickCount = Math.min(6, Math.max(2, Math.floor(chartWidth / 80)));
  const ticks: number[] = [];
  for (let i = 0; i <= tickCount; i++) {
    ticks.push((maxEnd * i) / tickCount);
  }

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
          {/* Agent labels (y-axis) */}
          {agents.map((agent, i) => {
            const cy = TOP_PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2;
            return (
              <text
                key={agent}
                x={LABEL_WIDTH - 6}
                y={cy + 3}
                textAnchor="end"
                fontSize={axisTick.fontSize}
                fill={axisTick.fill}
              >
                {agent.length > 10 ? agent.slice(0, 10) + "..." : agent}
              </text>
            );
          })}

          {/* Row separators */}
          {agents.map((_, i) => {
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
          {ticks.map((t) => {
            const tx = LABEL_WIDTH + xScale(t);
            return (
              <g key={`tick-${t}`}>
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
                  y2={TOP_PADDING + agents.length * ROW_HEIGHT}
                  stroke="currentColor"
                  strokeOpacity={0.04}
                  strokeDasharray="3 3"
                />
              </g>
            );
          })}

          {/* Bars */}
          {rows.map((row, i) => {
            const agentIndex = agents.indexOf(row.agent);
            if (agentIndex < 0) return null;
            const barY =
              TOP_PADDING + agentIndex * ROW_HEIGHT + (ROW_HEIGHT - BAR_HEIGHT) / 2;
            const barX = LABEL_WIDTH + xScale(row.start_ms);
            const barW = Math.max(xScale(row.duration_ms), 2); // minimum 2px width
            const color = row.kind === "tool" ? TOOL_COLOR : LLM_COLOR;

            return (
              <rect
                key={`bar-${i}`}
                x={barX}
                y={barY}
                width={barW}
                height={BAR_HEIGHT}
                fill={color}
                fillOpacity={0.75}
                rx={BAR_RADIUS}
                onMouseEnter={(e) => handleMouseEnter(row, e)}
                onMouseLeave={handleMouseLeave}
                style={{ cursor: "pointer" }}
              >
                <title>{`${row.agent} — ${row.label} (${formatMs(row.duration_ms)})`}</title>
              </rect>
            );
          })}

          {/* Tooltip */}
          {tooltip && (
            <foreignObject
              x={Math.min(tooltip.x + 12, LABEL_WIDTH + chartWidth - 160)}
              y={Math.max(tooltip.y - 50, 0)}
              width={160}
              height={60}
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
                <div style={{ fontWeight: 600 }}>{tooltip.row.agent}</div>
                <div>{tooltip.row.label}</div>
                <div>{formatMs(tooltip.row.duration_ms)}</div>
              </div>
            </foreignObject>
          )}
        </svg>
      </div>
    </div>
  );
}
