import { create } from "zustand";
import { fetchWithAuth } from "@/lib/api";
import type { ChartGroup } from "./chartStore";

export interface AgentSnapshot {
  name: string;
  after: string[];
  md_content: string;
  tools: string[] | null;
  model: string | null;
  retries: number;
}

export interface ConversationMessage {
  id: string;
  type: "agent" | "user" | "tool_call" | "system";
  nodeId?: string;
  content?: string;
  agentName?: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  status?: string;
  durationMs?: number;
  timestamp?: number;
}

export interface AgentIORecord {
  input_prompt: string;
  system_prompt?: string;
  output_result: unknown;
}

export interface RunSummary {
  run_id: string;
  workflow_name: string;
  status: string;
  inputs: Record<string, unknown>;
  created_at: string;
  batch_id?: string | null;
  user_id?: string | null;
}

export interface RunRecord {
  run_id: string;
  workflow_name: string;
  agents_snapshot: AgentSnapshot[];
  status: string;
  inputs: Record<string, unknown>;
  agent_io?: Record<string, AgentIORecord>;
  result: {
    outputs: Record<string, unknown>;
    errors: Record<string, string>;
    trace: Array<{
      agent_name: string;
      status: string;
      duration_ms: number;
      error: string | null;
      token_usage?: { input: number; output: number; total: number } | null;
    }>;
  } | null;
  conversation: ConversationMessage[];
  created_at: string;
  dag: {
    nodes: string[];
    edges: [string, string][];
    conditional_edges?: { from: string; to: string; label: string }[];
  } | null;
  chart_groups: {
    groups: Record<string, ChartGroup>;
    groupOrder: string[];
  } | null;
  events?: Array<{
    type: string;
    ts: number;
    payload: Record<string, unknown>;
  }>;
  _has_charts?: boolean;
  _has_events?: boolean;
}

interface RunHistoryState {
  runs: RunSummary[];
  loading: boolean;
  selectedRunId: string | null;
  selectedRunIds: Set<string>;
  isSelectMode: boolean;
  hasMore: boolean;
  totalCount: number;

  fetchRuns: (workflowName?: string, loadMore?: boolean) => Promise<void>;
  fetchRun: (runId: string, signal?: AbortSignal) => Promise<RunRecord | null>;
  fetchRunCharts: (runId: string) => Promise<RunRecord["chart_groups"]>;
  fetchRunEvents: (runId: string) => Promise<RunRecord["events"]>;
  selectRun: (runId: string | null) => void;
  toggleSelectMode: () => void;
  toggleRunSelection: (runId: string) => void;
  clearSelection: () => void;
  reset: () => void;
}

export const useRunHistoryStore = create<RunHistoryState>()((set, get) => ({
  runs: [],
  loading: false,
  selectedRunId: null,
  selectedRunIds: new Set<string>(),
  isSelectMode: false,
  hasMore: false,
  totalCount: 0,

  fetchRuns: async (workflowName?: string, loadMore = false) => {
    set({ loading: true });
    try {
      const { runs: currentRuns } = get();
      const offset = loadMore ? currentRuns.length : 0;
      const limit = 50;
      const params = new URLSearchParams();
      if (workflowName) params.set("workflow_name", workflowName);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      const r = await fetchWithAuth(`/api/runs?${params}`);
      if (r.ok) {
        const data = await r.json();
        const newRuns: RunSummary[] = data.runs;
        set({
          runs: loadMore ? [...currentRuns, ...newRuns] : newRuns,
          hasMore: data.has_more,
          totalCount: data.total,
          loading: false,
        });
      } else {
        console.error(`fetchRuns: ${r.status} ${r.statusText}`);
        set({ loading: false });
      }
    } catch (e) {
      console.error("fetchRuns failed:", e);
      set({ loading: false });
    }
  },

  fetchRun: async (runId: string, signal?: AbortSignal) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}`, { signal });
      if (r.ok) return await r.json();
    } catch (e: any) {
      if (e?.name === "AbortError") return null;
    }
    return null;
  },

  fetchRunCharts: async (runId: string) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}/charts`);
      if (r.ok) return await r.json();
    } catch {}
    return null;
  },

  fetchRunEvents: async (runId: string) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}/events`);
      if (r.ok) return await r.json();
    } catch {}
    return null;
  },

  selectRun: (runId) => set({ selectedRunId: runId }),

  toggleSelectMode: () =>
    set((s) => ({
      isSelectMode: !s.isSelectMode,
      selectedRunIds: s.isSelectMode ? new Set<string>() : s.selectedRunIds,
    })),

  toggleRunSelection: (runId) =>
    set((s) => {
      const next = new Set(s.selectedRunIds);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return { selectedRunIds: next };
    }),

  clearSelection: () => set({ selectedRunIds: new Set<string>() }),

  reset: () => set({ runs: [], loading: false, selectedRunId: null, selectedRunIds: new Set<string>(), isSelectMode: false, hasMore: false, totalCount: 0 }),
}));
