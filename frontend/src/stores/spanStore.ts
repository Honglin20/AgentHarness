import { create } from "zustand";

export interface SpanRecord {
  spanId: string;
  agentName: string;
  spanType: "llm" | "tool";
  startTs: number;
  endTs: number | null;
  model?: string;
  toolName?: string;
}

export interface WaterfallRow {
  agent: string;
  start_ms: number;
  duration_ms: number;
  kind: "llm" | "tool";
  label: string;
}

export interface SpanState {
  spans: Record<string, SpanRecord>;
  workflowStartTs: number | null;

  startSpan: (payload: {
    span_id: string;
    agent_name: string;
    span_type: "llm" | "tool";
    ts: number;
    model?: string;
    tool_name?: string;
  }) => void;

  endSpan: (spanId: string, ts: number) => void;

  setWorkflowStartTs: (ts: number) => void;

  computeWaterfallData: () => WaterfallRow[];

  reset: () => void;
}

const initialState = {
  spans: {} as Record<string, SpanRecord>,
  workflowStartTs: null as number | null,
};

export const useSpanStore = create<SpanState>()((set, get) => ({
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

  endSpan: (spanId, ts) =>
    set((state) => {
      const span = state.spans[spanId];
      if (!span) return state;
      return {
        spans: {
          ...state.spans,
          [spanId]: { ...span, endTs: ts },
        },
      };
    }),

  setWorkflowStartTs: (ts) => set({ workflowStartTs: ts }),

  computeWaterfallData: () => {
    const { spans, workflowStartTs } = get();
    const completed = Object.values(spans).filter((s) => s.endTs !== null);
    if (completed.length === 0) return [];

    // Determine baseline. Prefer workflowStartTs, but fall back to the earliest
    // span ts if the configured baseline is missing or wildly out of range
    // (e.g. legacy events where event.ts was monotonic seconds, not epoch ms).
    const minSpanTs = Math.min(...completed.map((s) => s.startTs));
    const ONE_DAY_MS = 24 * 60 * 60 * 1000;
    let baseline = workflowStartTs ?? minSpanTs;
    if (
      baseline == null ||
      minSpanTs - baseline < 0 ||
      minSpanTs - baseline > ONE_DAY_MS
    ) {
      baseline = minSpanTs;
    }

    const rows: WaterfallRow[] = [];
    for (const span of completed) {
      rows.push({
        agent: span.agentName,
        start_ms: Math.max(0, span.startTs - baseline),
        duration_ms: (span.endTs as number) - span.startTs,
        kind: span.spanType,
        label: span.spanType === "llm" ? (span.model ?? "LLM") : (span.toolName ?? "tool"),
      });
    }
    return rows;
  },

  reset: () => set(initialState),
}));
