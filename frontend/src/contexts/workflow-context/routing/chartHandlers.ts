/**
 * Chart and step summary event handlers.
 */

import type { EventHandler } from "./types";
import type { ChartRenderPayload, StepSummaryPayload } from "@/types/events";
import { payload } from "./utils";

export const chartHandlers: [string, EventHandler][] = [
  [
    "chart.render",
    (stores, event, _ctx) => {
      const p = payload<ChartRenderPayload>(event);
      // Accept three shapes:
      //   - nested: { chart: {label, title, chart_type, ...} }  (harness/tools/chart.py)
      //   - flat:   { label, title, chart_type, ... }            (plugins like perf_metrics)
      //   - ref:    { chart_ref: {label, title, chart_type} }    (deduped events sidecar)
      // Ref payloads lack full data — skip them (charts sidecar is the authoritative source).
      const chart = (p as any).chart ?? p;
      if (chart && (chart as any).label && !(p as any).chart_ref) {
        stores.chart.getState().addChart(chart as any);
      }
    },
  ],

  [
    "step.summary",
    (stores, event, _ctx) => {
      const p = payload<StepSummaryPayload>(event);
      stores.workflow.setState((state) => ({
        nodes: {
          ...state.nodes,
          [p.node_id]: {
            ...state.nodes[p.node_id],
            toolCallCount: p.node_tool_calls,
            llmCallCount: p.node_llm_calls,
          },
        },
      }));
    },
  ],
];
