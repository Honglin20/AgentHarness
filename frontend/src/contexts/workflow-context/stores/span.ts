import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { SpanState } from "@/stores/spanStore";

export function createSpanStore(
  workflowId: string,
): StoreApi<SpanState> {
  const initialState: SpanState = {
    spans: {},
    workflowStartTs: null,

    startSpan: (payload) => {
      /* Phase 2 实现 */
    },
    endSpan: (spanId, ts) => {
      /* Phase 2 实现 */
    },
    setWorkflowStartTs: (ts) => {
      /* Phase 2 实现 */
    },
    computeWaterfallData: () => [],
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<SpanState>()((set, get) => ({
    ...initialState,

    startSpan: (payload) =>
      set((state) => ({
        spans: {
          ...state.spans,
          [payload.span_id]: {
            spanId: payload.span_id,
            agentName: payload.agent_name,
            spanType: payload.span_type,
            startTs: payload.ts,
            endTs: null,
            model: payload.model,
            toolName: payload.tool_name,
          },
        },
      })),

    endSpan: (spanId, ts) => {
      const span = get().spans[spanId];
      if (!span) return;
      set((state) => ({
        spans: {
          ...state.spans,
          [spanId]: { ...span, endTs: ts },
        },
      }));
    },

    setWorkflowStartTs: (ts) => set({ workflowStartTs: ts }),

    computeWaterfallData: () => {
      const { spans, workflowStartTs } = get();
      if (!workflowStartTs) return [];

      const rows: import("@/stores/spanStore").WaterfallRow[] = [];
      for (const span of Object.values(spans)) {
        if (span.endTs === null) continue;
        rows.push({
          agent: span.agentName,
          start_ms: Math.max(0, span.startTs - workflowStartTs),
          duration_ms: span.endTs - span.startTs,
          kind: span.spanType,
          label: span.spanType === "llm" ? (span.model ?? "LLM") : (span.toolName ?? "tool"),
        });
      }
      return rows;
    },

    reset: () => set({ spans: {}, workflowStartTs: null }),
  }));
}
