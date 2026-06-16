/**
 * FitnessChart — NAS fitness trend across all cycle iterations.
 *
 * Phase 4 of long-run replay. Reads fitnessHistory from the scoped workflow
 * store (populated by hydrateFromSnapshot from the snapshot sidecar). Renders
 * a recharts line with optimal-record markers — same visual contract as
 * OptimalLineChartWidget so users see "is fitness improving across iters?"
 * at a glance.
 *
 * Empty / loading state: renders nothing (the parent tab hides the section
 * when fitnessHistory.length === 0 to avoid empty placeholders).
 */
"use client";

import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { useScopedWorkflowStore } from "@/contexts/workflow-context";
import { PALETTE, POSITIVE, NEUTRAL, LEGEND_STYLE, CHART_MARGIN, getGridProps, getAxisTick, getTooltipStyle } from "@/components/output/charts/chartTheme";

interface FitnessEntry {
  iter: number;
  best_fitness: number;
  best_strategy_id?: string;
  best_latency_ms?: number | null;
  best_metrics?: Record<string, unknown> | null;
  primary_metric?: string | null;
}

export function FitnessChart() {
  const history = useScopedWorkflowStore((s) => s.fitnessHistory) as FitnessEntry[];
  if (!history || history.length === 0) return null;

  // Compute optimal-so-far line — same algorithm as OptimalLineChartWidget.
  // For fitness, higher = better, so direction is "max".
  let accum = history[0].best_fitness;
  const data = history.map((h) => {
    const prev = accum;
    accum = Math.max(accum, h.best_fitness);
    return {
      iter: h.iter,
      fitness: h.best_fitness,
      optimal: accum,
      isRecord: accum !== prev,
      strategy_id: h.best_strategy_id,
      latency_ms: h.best_latency_ms,
    };
  });

  const gridProps = getGridProps();
  const axisTick = getAxisTick();
  const tooltipStyle = getTooltipStyle();

  return (
    <div className="rounded-lg border border-app-border bg-app-bg-primary p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-app-text-primary">
          Fitness Trend
        </h3>
        <span className="text-xs text-muted-foreground">
          {history.length} iter · best {data[data.length - 1].optimal.toFixed(4)}
        </span>
      </div>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="iter"
              {...axisTick}
            />
            <YAxis {...axisTick} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value: unknown, name: unknown) => {
                const v = typeof value === "number" ? value.toFixed(4) : String(value);
                if (name === "fitness") return [v, "this iter"];
                if (name === "optimal") return [v, "best so far"];
                return [v, String(name)];
              }}
              labelFormatter={(label) => `iter ${label}`}
            />
            <Line
              type="monotone"
              dataKey="fitness"
              stroke={NEUTRAL}
              strokeWidth={1.5}
              dot={{ r: 3, fill: NEUTRAL }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="optimal"
              stroke={POSITIVE}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex justify-center gap-4 text-[11px]" style={LEGEND_STYLE}>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: NEUTRAL }} />
          this iter best
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: POSITIVE }} />
          best-so-far
        </span>
      </div>
    </div>
  );
}
