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
}

interface RunHistoryState {
  runs: RunRecord[];
  loading: boolean;
  selectedRunId: string | null;

  fetchRuns: (workflowName?: string) => Promise<void>;
  fetchRun: (runId: string) => Promise<RunRecord | null>;
  selectRun: (runId: string | null) => void;
  reset: () => void;
}

export const useRunHistoryStore = create<RunHistoryState>()((set) => ({
  runs: [],
  loading: false,
  selectedRunId: null,

  fetchRuns: async (workflowName?: string) => {
    set({ loading: true });
    try {
      const params = workflowName ? `?workflow_name=${encodeURIComponent(workflowName)}` : "";
      const r = await fetchWithAuth(`/api/runs${params}`);
      if (r.ok) {
        const runs: RunRecord[] = await r.json();
        set({ runs, loading: false });
      } else {
        console.error(`fetchRuns: ${r.status} ${r.statusText}`);
        set({ loading: false });
      }
    } catch (e) {
      console.error("fetchRuns failed:", e);
      set({ loading: false });
    }
  },

  fetchRun: async (runId: string) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}`);
      if (r.ok) return await r.json();
    } catch {}
    return null;
  },

  selectRun: (runId) => set({ selectedRunId: runId }),

  reset: () => set({ runs: [], loading: false, selectedRunId: null }),
}));
