import { create } from "zustand";
import { fetchWithAuth } from "@/lib/api";
import type { ChartGroup } from "./chartStore";
import type { ConversationMessageDTO } from "@/lib/conversion/dtoToMessage";

export interface AgentSnapshot {
  name: string;
  after: string[];
  md_content: string;
  tools: string[] | null;
  model: string | null;
  retries: number;
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

/**
 * Outline summary sidecar DTO (snake_case from backend). Structurally
 * isomorphic to `OutlineItem` (`frontend/src/components/outline/types.ts`) —
 * `outlineSummaryToItems` does a 1:1 camelCase cast. Sidecar is the source of
 * truth in replay mode; live mode derives from conversation as before.
 */
export interface OutlineSummaryItem {
  key: string;
  node_id: string;
  iteration: number;
  is_latest_iter: boolean;
  iter_count: number;
  name: string;
  first_ts: number;
  status: "idle" | "running" | "waiting-for-user" | "completed" | "failed" | "retrying";
  activity: Record<string, unknown>;
  badges: Array<{ kind: string; text: string; title?: string }>;
  order: number;
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
  /**
   * Conversation messages. Sidecar-only since `server/_helpers.py` strips
   * `conversation` to `None` on the detail endpoint and exposes the data via
   * `GET /runs/{id}/conversation` (gated by `_has_conversation`).
   *
   * Optional because legacy / inline persisted runs may still carry it on the
   * main record; consumers should always read via `?? []` or the sidecar fetch
   * in `hydrateReplay.loadSidecars`.
   */
  conversation?: ConversationMessageDTO[] | null;
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
  /**
   * Outline sidecar exists. When true, `fetchRunOutline` returns the
   * pre-computed per-(nodeId, iter) summary so the outline can render
   * without scanning the full conversation. False on legacy runs and
   * when outline computation failed at save time — frontend then derives
   * from conversation as before.
   */
  _has_outline?: boolean;
  /** Per-node TODO steps snapshot, saved at workflow completion. */
  todo_steps?: Record<string, Array<{
    task_id: string;
    content: string;
    activeForm: string;
    status: string;
    detail: string | null;
  }>> | null;
}

interface RunHistoryState {
  runs: RunSummary[];
  loading: boolean;
  selectedRunId: string | null;
  selectedRunIds: Set<string>;
  isSelectMode: boolean;
  hasMore: boolean;
  totalCount: number;

  /**
   * Initial load / explicit reset. Replaces `runs` with the first page
   * (INITIAL_PAGE_LIMIT) and writes the cache. Use for: mount, user switch,
   * workflow switch where a fresh slate is desired. **Do not** use for
   * polling — that's what `refreshRuns` is for, since fetchRuns would
   * truncate a list the user has expanded via loadMore.
   */
  fetchRuns: (workflowName?: string) => Promise<void>;

  /**
   * User clicked "Load more". Appends the next page (limit=50) to `runs`
   * and updates the cache with the merged list. Bypasses the cache check
   * (a loadMore always needs fresh data) but still participates in
   * in-flight dedup so rapid clicks coalesce.
   */
  loadMoreRuns: (workflowName?: string) => Promise<void>;

  /**
   * Polling-friendly refresh. Fetches with `limit = max(current.length,
   * INITIAL_PAGE_LIMIT)` so a list the user expanded via loadMore is
   * preserved at its current length instead of being truncated back to
   * the first page. Result replaces `runs` (status / icon updates flow
   * through naturally; newly-created runs appear at the top; the oldest
   * visible run scrolls off the window).
   *
   * Respects the cache TTL — if a refresh fired <3s ago, this is a no-op.
   */
  refreshRuns: (workflowName?: string) => Promise<void>;

  fetchRun: (runId: string, signal?: AbortSignal) => Promise<RunRecord | null>;
  fetchRunCharts: (runId: string) => Promise<RunRecord["chart_groups"]>;
  fetchRunEvents: (runId: string) => Promise<RunRecord["events"]>;
  fetchRunConversation: (runId: string) => Promise<RunRecord["conversation"] | null>;
  /**
   * Fetch the outline summary sidecar. Returns null when the sidecar is
   * absent (legacy run / computation failed) — caller falls back to
   * deriving from conversation. Mirrors `fetchRunCharts`/`fetchRunEvents`.
   */
  fetchRunOutline: (runId: string) => Promise<OutlineSummaryItem[] | null>;
  selectRun: (runId: string | null) => void;
  toggleSelectMode: () => void;
  toggleRunSelection: (runId: string) => void;
  clearSelection: () => void;
  reset: () => void;
}

// ── In-memory cache + dedup ─────────────────────────────────────────────
//
// The sidebar hits the runs endpoint from many sources: terminal lifecycle
// events, manual refresh, mount, polling. Without dedup we'd fire 3-5x
// the needed requests on every workflow completion. The cache holds the
// last successful fetch per key (workflowName) for FETCH_DEDUP_MS; within
// that window repeat calls of the same flavour are no-ops.
//
// loadMore calls bypass the cache check (always fetch the next page) but
// still go through in-flight dedup so two near-simultaneous "load more"
// clicks don't double-fetch.
const FETCH_DEDUP_MS = 3000;
/** Initial sidebar page size — small for fast first paint, expandable via "Load more". */
const INITIAL_PAGE_LIMIT = 5;
/** Page size used when the user explicitly asks for more history. */
const LOAD_MORE_PAGE_LIMIT = 50;

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

// ── Per-run Last-Modified cache ─────────────────────────────────────────
//
// The backend's GET /api/runs/{id} honours If-Modified-Since and returns
// 304 when the run's persisted file mtime hasn't advanced. We pair that
// with a client-side cache so a 304 yields the previously-fetched body
// instead of `null` — otherwise the sidebar's click handler silently
// swallowed the second click on the same run.
//
// Lifecycle: entries live until invalidated. Call invalidateRunCache(runId)
// when a run is known to have changed (delete, rerun, resume).
interface RunCacheEntry {
  run: RunRecord;
  /** HTTP-date string from the server's Last-Modified response header. */
  lastModified: string | null;
}
const _runCache = new Map<string, RunCacheEntry>();

export function invalidateRunCache(runId?: string): void {
  if (runId === undefined) {
    _runCache.clear();
    return;
  }
  _runCache.delete(runId);
}

// ── Private: shared fetch engine ────────────────────────────────────────
//
// Three fetch flavours (initial / append / refresh) share the same cache,
// in-flight dedup, and setState plumbing. Each flavour supplies its own
// limit/offset strategy and merge function; the engine handles the rest.

interface FetchFlavour {
  /** Skip the cache check entirely (loadMore always wants the network). */
  bypassCache?: boolean;
  /** Compute request limit based on current state (e.g. current list length). */
  getLimit: (currentCount: number) => number;
  /** Compute request offset based on current state. */
  getOffset: (currentCount: number) => number;
  /** Combine the current list with the freshly-fetched page. */
  merge: (current: RunSummary[], fetched: RunSummary[]) => RunSummary[];
}

const FETCH_FLAVOURS: Record<"initial" | "append" | "refresh", FetchFlavour> = {
  initial: {
    getLimit: () => INITIAL_PAGE_LIMIT,
    getOffset: () => 0,
    merge: (_current, fetched) => fetched,
  },
  append: {
    bypassCache: true,
    getLimit: () => LOAD_MORE_PAGE_LIMIT,
    getOffset: (currentCount) => currentCount,
    merge: (current, fetched) => [...current, ...fetched],
  },
  refresh: {
    // Preserve list length: if user has loaded 55 runs, refresh fetches
    // 55 (not 5) so the expanded list isn't truncated by polling.
    getLimit: (currentCount) => Math.max(currentCount, INITIAL_PAGE_LIMIT),
    getOffset: () => 0,
    // The fetched slice IS the new state — server returns newest-first,
    // so a refresh naturally surfaces new runs at the top and scrolls the
    // oldest visible run off the window.
    merge: (_current, fetched) => fetched,
  },
};

interface PageData {
  runs: RunSummary[];
  total: number;
  has_more: boolean;
}

async function _fetchPage(
  workflowName: string | undefined,
  limit: number,
  offset: number,
): Promise<PageData | null> {
  const params = new URLSearchParams();
  if (workflowName) params.set("workflow_name", workflowName);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  try {
    const r = await fetchWithAuth(`/api/runs?${params}`);
    if (!r.ok) {
      console.error(`fetchRuns: ${r.status} ${r.statusText}`);
      return null;
    }
    return (await r.json()) as PageData;
  } catch (e) {
    console.error("fetchRuns failed:", e);
    return null;
  }
}

type StoreSet = (partial: Partial<RunHistoryState> | ((s: RunHistoryState) => Partial<RunHistoryState>)) => void;
type StoreGet = () => RunHistoryState;

/**
 * Defensive fallback: server returned 304 to a request that didn't carry
 * If-Modified-Since (e.g. first fetch, or the cache was wiped between the
 * conditional check and the response). Should not happen in normal flow,
 * but we mustn't deadlock the caller — re-fetch unconditionally and cache
 * the result.
 */
async function _fetchRunUnconditional(runId: string, signal?: AbortSignal): Promise<RunRecord | null> {
  try {
    const r = await fetchWithAuth(`/api/runs/${runId}`, { signal });
    if (!r.ok) return null;
    const run = (await r.json()) as RunRecord;
    _runCache.set(runId, {
      run,
      lastModified: r.headers.get("Last-Modified"),
    });
    return run;
  } catch (e: any) {
    if (e?.name === "AbortError") return null;
    return null;
  }
}

/**
 * Cache + in-flight dedup + setState plumbing, shared across the three
 * public methods. Each call site picks a flavour; the engine decides
 * whether to short-circuit on cache, await an in-flight request, or
 * fire a new one.
 *
 * The cache entry stores the post-merge `runs` list, so once any flavour
 * succeeds the cache reflects what's in the store — subsequent cache hits
 * (within TTL) skip both the network AND setState, which is what keeps
 * polling cheap.
 */
async function _executeFetch(
  set: StoreSet,
  get: StoreGet,
  flavourName: "initial" | "append" | "refresh",
  workflowName?: string,
): Promise<void> {
  const key = runsCacheKey(workflowName);
  const flavour = FETCH_FLAVOURS[flavourName];

  // Cache check (skipped for loadMore).
  if (!flavour.bypassCache) {
    const cached = _runsCache.get(key);
    if (cached && Date.now() - cached.fetchedAt < FETCH_DEDUP_MS) {
      return;
    }
  }

  // In-flight dedup: don't fire a second request for the same key while
  // the first is still pending — wait for it, then re-evaluate. The
  // second caller either hits the now-populated cache (no-op) or proceeds
  // if the first one failed / cleared the inflight slot.
  const pending = _inflight.get(key);
  if (pending) {
    await pending;
    // Re-check cache after awaiting — the in-flight request may have just
    // populated it. Avoids a redundant network call in the common "two
    // effects fired at once" case.
    if (!flavour.bypassCache) {
      const cached = _runsCache.get(key);
      if (cached && Date.now() - cached.fetchedAt < FETCH_DEDUP_MS) {
        return;
      }
    }
    // Cache miss after awaiting → fall through and fetch.
  }

  const promise = (async () => {
    set({ loading: true });
    try {
      const currentCount = get().runs.length;
      const data = await _fetchPage(
        workflowName,
        flavour.getLimit(currentCount),
        flavour.getOffset(currentCount),
      );
      if (!data) {
        set({ loading: false });
        return;
      }
      const current = get().runs;
      const merged = flavour.merge(current, data.runs);
      set({
        runs: merged,
        hasMore: data.has_more,
        totalCount: data.total,
        loading: false,
      });
      _runsCache.set(key, {
        runs: merged,
        total: data.total,
        hasMore: data.has_more,
        fetchedAt: Date.now(),
      });
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
}



export const useRunHistoryStore = create<RunHistoryState>()((set, get) => ({
  runs: [],
  loading: false,
  selectedRunId: null,
  selectedRunIds: new Set<string>(),
  isSelectMode: false,
  hasMore: false,
  totalCount: 0,

  /**
   * Shared engine — see FETCH_FLAVOURS for per-mode strategy. Encapsulates
   * the cache + in-flight dedup so the three public methods stay tiny and
   * each mode's intent is self-documenting at the call site.
   *
   * Cache hit policy: return WITHOUT calling set(). set() triggers
   * subscriber notifications; combined with inline useShallow selectors
   * (which return a fresh dict every render) it caused an unbounded
   * request loop — observed 92 list_runs calls during one workflow run
   * before this rule was added.
   */
  fetchRuns: (workflowName) => _executeFetch(set, get, "initial", workflowName),
  loadMoreRuns: (workflowName) => _executeFetch(set, get, "append", workflowName),
  refreshRuns: (workflowName) => _executeFetch(set, get, "refresh", workflowName),

  fetchRun: async (runId: string, signal?: AbortSignal) => {
    const cached = _runCache.get(runId);
    const headers: Record<string, string> = {};
    if (cached?.lastModified) {
      headers["If-Modified-Since"] = cached.lastModified;
    }
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}`, { headers, signal });
      // 304 = server says "your cache is still fresh". The previous code
      // returned null here, which the click handler treated as failure —
      // the user clicked but nothing happened. Now we surface the cached
      // body so the click is responsive.
      if (r.status === 304) {
        return cached ? cached.run : _fetchRunUnconditional(runId, signal);
      }
      if (r.ok) {
        const run = (await r.json()) as RunRecord;
        _runCache.set(runId, {
          run,
          lastModified: r.headers.get("Last-Modified"),
        });
        return run;
      }
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

  fetchRunOutline: async (runId: string) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}/outline`);
      if (r.ok) {
        const data = await r.json();
        return Array.isArray(data) ? (data as OutlineSummaryItem[]) : null;
      }
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
