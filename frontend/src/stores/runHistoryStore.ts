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
  _has_conversation?: boolean;
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
  fetchRunConversation: (runId: string) => Promise<RunRecord["conversation"] | null>;
  selectRun: (runId: string | null) => void;
  toggleSelectMode: () => void;
  toggleRunSelection: (runId: string) => void;
  clearSelection: () => void;
  reset: () => void;
}

// ── In-memory cache + dedup ─────────────────────────────────────────────
//
// Sidebar refreshes hit fetchRuns from many sources: terminal lifecycle
// events, manual refresh, mount, polling. Without dedup we'd fire 3-5x
// the needed requests on every workflow completion. The cache holds the
// last successful fetch per key (workflowName) for ~3s; within that window
// repeat calls are no-ops.
//
// loadMore calls bypass the cache (always fetch the next page) but still
// go through the in-flight dedup so two near-simultative "load more"
// clicks don't double-fetch.
const FETCH_DEDUP_MS = 3000;
/** Initial sidebar page size — small for fast first paint, expandable via "Load more". */
const INITIAL_PAGE_LIMIT = 5;
interface CacheEntry {
  runs: RunSummary[];
  total: number;
  hasMore: boolean;
  fetchedAt: number;
}
const _runsCache = new Map<string, CacheEntry>();
const _inflight = new Map<string, Promise<void>>();

function runsCacheKey(workflowName?: string): string {
  return workflowName || "__all__";
}

export function invalidateRunsCache(workflowName?: string): void {
  // undefined wildcard — drop everything (used by terminal lifecycle events
  // that may affect any workflow's run list, e.g. delete).
  if (workflowName === undefined) {
    _runsCache.clear();
    return;
  }
  _runsCache.delete(runsCacheKey(workflowName));
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
    const key = runsCacheKey(workflowName);

    // Cache hit: same key fetched within FETCH_DEDUP_MS and caller isn't
    // asking for a new page → no-op. We must NOT call set() here, even with
    // identical values — set() triggers subscriber notifications and, with
    // inline useShallow selectors that produce a new dict every render,
    // causes every subscriber to re-render. That re-render can re-trigger
    // the effect that called fetchRuns, producing an unbounded request
    // storm (we observed 92 list_runs calls during one workflow run).
    if (!loadMore) {
      const cached = _runsCache.get(key);
      if (cached && Date.now() - cached.fetchedAt < FETCH_DEDUP_MS) {
        return;
      }
    }

    // In-flight dedup: don't fire a second request for the same key while
    // the first is still pending — wait for it instead.
    const pending = _inflight.get(key);
    if (pending) {
      await pending;
      return;
    }

    const promise = (async () => {
      set({ loading: true });
      try {
        const { runs: currentRuns } = get();
        const offset = loadMore ? currentRuns.length : 0;
        // Initial page is small (5) so sidebar first paint is snappy; user
        // expands via "Load more runs" button. Subsequent pages can be larger
        // since the user has signaled they want history.
        const limit = loadMore ? 50 : INITIAL_PAGE_LIMIT;
        const params = new URLSearchParams();
        if (workflowName) params.set("workflow_name", workflowName);
        params.set("limit", String(limit));
        params.set("offset", String(offset));
        const r = await fetchWithAuth(`/api/runs?${params}`);
        if (r.ok) {
          const data = await r.json();
          const newRuns: RunSummary[] = data.runs;
          const merged = loadMore ? [...currentRuns, ...newRuns] : newRuns;
          set({
            runs: merged,
            hasMore: data.has_more,
            totalCount: data.total,
            loading: false,
          });
          // Cache first-page results (loadMore appends; can't cache without
          // a stable shape, so leave the existing entry alone).
          if (!loadMore) {
            _runsCache.set(key, {
              runs: merged,
              total: data.total,
              hasMore: data.has_more,
              fetchedAt: Date.now(),
            });
          }
        } else {
          console.error(`fetchRuns: ${r.status} ${r.statusText}`);
          set({ loading: false });
        }
      } catch (e) {
        console.error("fetchRuns failed:", e);
        set({ loading: false });
      }
    })();

    _inflight.set(key, promise);
    try {
      await promise;
    } finally {
      _inflight.delete(key);
    }
  },

  fetchRun: async (runId: string, signal?: AbortSignal) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}`, { signal });
      if (r.status === 304) return null; // caller can keep its cached run
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

  fetchRunConversation: async (runId: string) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}/conversation`);
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
