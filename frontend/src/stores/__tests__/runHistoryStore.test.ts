/**
 * Lock-in tests for runHistoryStore.
 *
 * These tests cover behavior that must remain stable across the upcoming
 * fetchRuns refactor (split into fetch / loadMore / refresh). They use only
 * `fetchRuns()` with no arguments — a call shape that survives the refactor
 * because its "initial load / replace" semantics don't change.
 *
 * Behaviors locked in:
 *   - Initial load populates store + cache
 *   - Cache hit within TTL skips the request
 *   - Cache expiry re-fetches
 *   - In-flight dedup shares a single promise between concurrent callers
 *   - invalidateRunsCache forces the next call to bypass the cache
 *   - HTTP non-2xx logs and clears loading flag without crashing
 *
 * New tests for loadMoreRuns / refreshRuns (the methods the refactor adds)
 * live alongside these once the refactor lands.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  useRunHistoryStore,
  invalidateRunsCache,
  invalidateRunCache,
} from "@/stores/runHistoryStore";
import {
  mockFetch,
  createMockRunSummary,
  createMockRunRecord,
  createMockRunSummaries,
  flushAsync,
  type MockFetchController,
} from "./helpers";

describe("runHistoryStore — lock-in", () => {
  let ctrl: MockFetchController;

  beforeEach(() => {
    useRunHistoryStore.getState().reset();
    invalidateRunsCache();
    ctrl = mockFetch();
  });

  afterEach(() => {
    ctrl.restore();
    vi.useRealTimers();
  });

  it("fetchRuns initial load populates store + cache", async () => {
    const runs = createMockRunSummaries(3);
    ctrl.push({
      body: { runs, total: 3, has_more: false },
    });

    await useRunHistoryStore.getState().fetchRuns();

    const state = useRunHistoryStore.getState();
    expect(state.runs).toHaveLength(3);
    expect(state.runs).toEqual(runs);
    expect(state.totalCount).toBe(3);
    expect(state.hasMore).toBe(false);
    expect(state.loading).toBe(false);
  });

  it("fetchRuns sets hasMore=true when server reports more", async () => {
    ctrl.push({
      body: { runs: createMockRunSummaries(5), total: 50, has_more: true },
    });
    await useRunHistoryStore.getState().fetchRuns();
    expect(useRunHistoryStore.getState().hasMore).toBe(true);
    expect(useRunHistoryStore.getState().totalCount).toBe(50);
  });

  it("cache hit within TTL skips the request entirely", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);

    // Second call should hit the cache — no new fetch.
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);
  });

  it("cache expiry triggers a re-fetch", async () => {
    vi.useFakeTimers();
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);

    // Advance past FETCH_DEDUP_MS (3s).
    vi.advanceTimersByTime(4000);

    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(2);
    expect(useRunHistoryStore.getState().runs).toHaveLength(3);
  });

  it("in-flight dedup shares a single promise between concurrent callers", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });

    // Fire two concurrent calls — both should await the same underlying fetch.
    const p1 = useRunHistoryStore.getState().fetchRuns();
    const p2 = useRunHistoryStore.getState().fetchRuns();
    await Promise.all([p1, p2]);

    expect(ctrl.callCount()).toBe(1);
  });

  it("invalidateRunsCache() forces next call to bypass cache", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);

    invalidateRunsCache();

    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(2);
  });

  it("invalidateRunsCache(undefined) drops all keys (wildcard)", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);

    // Wildcard invalidation.
    invalidateRunsCache(undefined);

    ctrl.push({ body: { runs: createMockRunSummaries(4), total: 4, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(2);
  });

  it("HTTP error logs and clears loading flag without crashing", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    ctrl.push({ status: 500 });

    await useRunHistoryStore.getState().fetchRuns();

    expect(useRunHistoryStore.getState().loading).toBe(false);
    expect(useRunHistoryStore.getState().runs).toEqual([]);
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it("reset() clears all state", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(useRunHistoryStore.getState().runs).toHaveLength(3);

    useRunHistoryStore.getState().reset();
    const s = useRunHistoryStore.getState();
    expect(s.runs).toEqual([]);
    expect(s.hasMore).toBe(false);
    expect(s.totalCount).toBe(0);
    expect(s.loading).toBe(false);
    expect(s.selectedRunId).toBeNull();
  });

  it("selectRun / toggleSelectMode / toggleRunSelection mutate selection state", () => {
    const store = useRunHistoryStore.getState();
    store.selectRun("run-xyz");
    expect(useRunHistoryStore.getState().selectedRunId).toBe("run-xyz");

    store.toggleSelectMode();
    expect(useRunHistoryStore.getState().isSelectMode).toBe(true);

    store.toggleRunSelection("run-a");
    store.toggleRunSelection("run-b");
    expect(useRunHistoryStore.getState().selectedRunIds.has("run-a")).toBe(true);
    expect(useRunHistoryStore.getState().selectedRunIds.has("run-b")).toBe(true);

    store.toggleRunSelection("run-a");
    expect(useRunHistoryStore.getState().selectedRunIds.has("run-a")).toBe(false);

    store.clearSelection();
    expect(useRunHistoryStore.getState().selectedRunIds.size).toBe(0);
  });

  it("fetchRuns() with no workflow_name uses __all__ cache key", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(2), total: 2, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);
    // Subsequent call (any workflowName === undefined) should hit __all__ cache.
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);
  });

  it("returns a fulfilled promise (no throw) on the happy path", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(1), total: 1, has_more: false } });
    await expect(useRunHistoryStore.getState().fetchRuns()).resolves.toBeUndefined();
  });

  it("flushAsync yields to microtasks after fetch resolves", async () => {
    const seen: string[] = [];
    ctrl.push({ body: { runs: createMockRunSummaries(1), total: 1, has_more: false } });
    promiseMicrotask(() => seen.push("microtask"));
    await useRunHistoryStore.getState().fetchRuns();
    await flushAsync();
    expect(seen).toEqual(["microtask"]);
  });
});

/**
 * Tests for the split API: fetchRuns / loadMoreRuns / refreshRuns.
 *
 * These tests cover the refactor's contract — specifically the bug fix
 * where polling used to truncate a list the user had expanded via
 * "Load more".
 */
describe("runHistoryStore — split API (fetchRuns / loadMoreRuns / refreshRuns)", () => {
  let ctrl: MockFetchController;

  beforeEach(() => {
    useRunHistoryStore.getState().reset();
    invalidateRunsCache();
    ctrl = mockFetch();
  });

  afterEach(() => {
    ctrl.restore();
  });

  it("fetchRuns initial load uses INITIAL_PAGE_LIMIT", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 50, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();

    expect(ctrl.callCount()).toBe(1);
    const callUrl = ctrl.mock.mock.calls[0][0] as string;
    expect(callUrl).toContain("limit=5");
    expect(callUrl).toContain("offset=0");
  });

  it("loadMoreRuns appends to existing list and preserves length", async () => {
    // Seed with 5 runs (initial load).
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 55, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(useRunHistoryStore.getState().runs).toHaveLength(5);

    // User clicks "Load more".
    ctrl.push({ body: { runs: createMockRunSummaries(50), total: 55, has_more: false } });
    await useRunHistoryStore.getState().loadMoreRuns();

    expect(useRunHistoryStore.getState().runs).toHaveLength(55);
    const loadMoreUrl = ctrl.mock.mock.calls[1][0] as string;
    expect(loadMoreUrl).toContain("offset=5");
    expect(loadMoreUrl).toContain("limit=50");
  });

  it("loadMoreRuns bypasses cache (always fetches a fresh page)", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 50, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();
    expect(ctrl.callCount()).toBe(1);

    // Even immediately (cache still fresh for "initial"), loadMore must fetch.
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 50, has_more: true } });
    await useRunHistoryStore.getState().loadMoreRuns();
    expect(ctrl.callCount()).toBe(2);
  });

  it("refreshRuns after loadMore preserves list length (the bug-fix case)", async () => {
    // Seed: 5 runs.
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 55, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();

    // User loads more → 55 runs.
    ctrl.push({ body: { runs: createMockRunSummaries(50), total: 55, has_more: false } });
    await useRunHistoryStore.getState().loadMoreRuns();
    expect(useRunHistoryStore.getState().runs).toHaveLength(55);

    // 30s polling fires refreshRuns. Force cache expiry (the polling path
    // also calls invalidateRunsCache on terminal events, so this matches
    // production behaviour).
    invalidateRunsCache();

    // The fetch must request 55 (not 5), otherwise the response would
    // truncate the sidebar back to 5.
    ctrl.push({ body: { runs: createMockRunSummaries(55), total: 55, has_more: false } });
    await useRunHistoryStore.getState().refreshRuns();

    expect(useRunHistoryStore.getState().runs).toHaveLength(55);
    const refreshUrl = ctrl.mock.mock.calls[2][0] as string;
    expect(refreshUrl).toContain("offset=0");
    expect(refreshUrl).toContain("limit=55"); // ← preserves loaded range
  });

  it("refreshRuns on a short list falls back to INITIAL_PAGE_LIMIT", async () => {
    // Initial 3 runs (less than INITIAL_PAGE_LIMIT). refreshRuns must still
    // request at least INITIAL_PAGE_LIMIT so newly-created runs show up.
    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();

    invalidateRunsCache();

    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 5, has_more: false } });
    await useRunHistoryStore.getState().refreshRuns();

    const refreshUrl = ctrl.mock.mock.calls[1][0] as string;
    expect(refreshUrl).toContain("limit=5");
  });

  it("refreshRuns surfaces newly-created runs at the top", async () => {
    const initialRuns = createMockRunSummaries(3);
    ctrl.push({ body: { runs: initialRuns, total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();

    invalidateRunsCache();

    // Server now has 1 additional new run at the top.
    const newRun = createMockRunSummary({ status: "running" });
    const refreshed = [newRun, ...initialRuns];
    ctrl.push({ body: { runs: refreshed, total: 4, has_more: false } });
    await useRunHistoryStore.getState().refreshRuns();

    const runs = useRunHistoryStore.getState().runs;
    expect(runs[0].run_id).toBe(newRun.run_id);
    expect(runs).toHaveLength(4);
  });

  it("refreshRuns respects cache TTL — second call within 3s is a no-op", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 5, has_more: false } });
    await useRunHistoryStore.getState().refreshRuns();
    expect(ctrl.callCount()).toBe(1);

    await useRunHistoryStore.getState().refreshRuns();
    expect(ctrl.callCount()).toBe(1);
  });

  it("refreshRuns after loadMore within cache TTL is a no-op", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 55, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();

    ctrl.push({ body: { runs: createMockRunSummaries(50), total: 55, has_more: false } });
    await useRunHistoryStore.getState().loadMoreRuns();
    expect(ctrl.callCount()).toBe(2);

    // Immediate refresh — should hit cache (loadMore just updated it).
    await useRunHistoryStore.getState().refreshRuns();
    expect(ctrl.callCount()).toBe(2);
    expect(useRunHistoryStore.getState().runs).toHaveLength(55);
  });

  it("concurrent refreshRuns + loadMoreRuns coalesce via in-flight dedup", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 50, has_more: true } });
    await useRunHistoryStore.getState().fetchRuns();

    // Fire refresh and loadMore simultaneously. In-flight dedup should
    // collapse them to a single network call.
    ctrl.push({ body: { runs: createMockRunSummaries(5), total: 50, has_more: true } });
    const p1 = useRunHistoryStore.getState().refreshRuns();
    const p2 = useRunHistoryStore.getState().loadMoreRuns();
    await Promise.all([p1, p2]);

    expect(ctrl.callCount()).toBe(2); // initial + at most one of refresh/loadMore
  });

  it("invalidateRunsCache + refreshRuns re-fetches after terminal event", async () => {
    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();

    invalidateRunsCache();

    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().refreshRuns();
    expect(ctrl.callCount()).toBe(2);
  });

  it("refreshRuns on HTTP error clears loading, keeps prior runs", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    ctrl.push({ body: { runs: createMockRunSummaries(3), total: 3, has_more: false } });
    await useRunHistoryStore.getState().fetchRuns();
    const initialRunIds = useRunHistoryStore.getState().runs.map((r) => r.run_id);

    invalidateRunsCache();
    ctrl.push({ status: 500 });
    await useRunHistoryStore.getState().refreshRuns();

    expect(useRunHistoryStore.getState().loading).toBe(false);
    // Prior runs are preserved — refresh failure must not blank the sidebar.
    expect(useRunHistoryStore.getState().runs.map((r) => r.run_id)).toEqual(initialRunIds);
    errSpy.mockRestore();
  });
});

/**
 * fetchRun Last-Modified cache — the bug fix for "user clicks the same run
 * twice, second click does nothing because server returned 304 and we
 * translated that to null".
 *
 * Backend contract (verified server-side): GET /api/runs/{id} returns
 * Last-Modified header, honours If-Modified-Since, returns 304 on match.
 */
describe("runHistoryStore — fetchRun Last-Modified cache", () => {
  let ctrl: MockFetchController;

  beforeEach(() => {
    invalidateRunCache();
    ctrl = mockFetch();
  });

  afterEach(() => {
    ctrl.restore();
  });

  it("first fetch stores the run + Last-Modified header", async () => {
    const run = createMockRunRecord({ run_id: "r1" });
    ctrl.push({
      body: run,
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });

    const result = await useRunHistoryStore.getState().fetchRun("r1");
    expect(result).toEqual(run);
    expect(ctrl.callCount()).toBe(1);
  });

  it("second fetch sends If-Modified-Since; 304 returns cached run (not null)", async () => {
    const run = createMockRunRecord({ run_id: "r1" });
    ctrl.push({
      body: run,
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    // Second call — server returns 304. Caller must NOT receive null.
    ctrl.push({ status: 304 });
    const result = await useRunHistoryStore.getState().fetchRun("r1");

    expect(result).toEqual(run); // ← the bug fix
    expect(ctrl.callCount()).toBe(2);

    // Verify If-Modified-Since was sent on the second request.
    const secondCallInit = ctrl.mock.mock.calls[1][1] as RequestInit;
    const headers = new Headers(secondCallInit.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBe("Wed, 01 Jun 2026 00:00:00 GMT");
  });

  it("first-ever fetch does not send If-Modified-Since (no cached value)", async () => {
    ctrl.push({ body: createMockRunRecord({ run_id: "r1" }) });
    await useRunHistoryStore.getState().fetchRun("r1");

    const init = ctrl.mock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBeNull();
  });

  it("200 response with newer mtime updates the cached run", async () => {
    const v1 = createMockRunRecord({ run_id: "r1", status: "running" });
    ctrl.push({
      body: v1,
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    // Server says it changed — 200 with new body.
    const v2 = createMockRunRecord({ run_id: "r1", status: "completed" });
    ctrl.push({
      body: v2,
      headers: { "Last-Modified": "Thu, 02 Jun 2026 00:00:00 GMT" },
    });
    const result = await useRunHistoryStore.getState().fetchRun("r1");

    expect(result).toEqual(v2);
    expect(result?.status).toBe("completed");
  });

  it("invalidateRunCache(runId) forces next call to skip conditional", async () => {
    ctrl.push({
      body: createMockRunRecord({ run_id: "r1" }),
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    invalidateRunCache("r1");

    // After invalidation, no If-Modified-Since should be sent.
    ctrl.push({
      body: createMockRunRecord({ run_id: "r1" }),
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    const init = ctrl.mock.mock.calls[1][1] as RequestInit;
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBeNull();
  });

  it("invalidateRunCache() wildcard drops all entries", async () => {
    ctrl.push({
      body: createMockRunRecord({ run_id: "r1" }),
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    invalidateRunCache(); // wildcard

    ctrl.push({
      body: createMockRunRecord({ run_id: "r1" }),
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");

    const init = ctrl.mock.mock.calls[1][1] as RequestInit;
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBeNull();
  });

  it("AbortError returns null and leaves cache untouched", async () => {
    // Pre-seed cache so we can verify it's not modified on abort.
    ctrl.push({
      body: createMockRunRecord({ run_id: "r1" }),
      headers: { "Last-Modified": "Wed, 01 Jun 2026 00:00:00 GMT" },
    });
    await useRunHistoryStore.getState().fetchRun("r1");
    expect(ctrl.callCount()).toBe(1);

    // Simulate abort: mock fetch that throws AbortError.
    const original = global.fetch;
    const ac = new AbortController();
    ac.abort();
    global.fetch = vi.fn(async () => {
      const e = new Error("aborted");
      e.name = "AbortError";
      throw e;
    });

    try {
      const result = await useRunHistoryStore.getState().fetchRun("r1", ac.signal);
      expect(result).toBeNull();
    } finally {
      global.fetch = original;
    }

    // Cache should still be intact — next call should send If-Modified-Since.
    ctrl.push({ status: 304 });
    const result = await useRunHistoryStore.getState().fetchRun("r1");
    expect(result).not.toBeNull();
  });

  it("server 200 without Last-Modified header caches run with null mtime", async () => {
    // Server doesn't send Last-Modified — cache stores null. Subsequent
    // fetches should not send If-Modified-Since.
    ctrl.push({ body: createMockRunRecord({ run_id: "r1" }) /* no headers */ });
    await useRunHistoryStore.getState().fetchRun("r1");

    ctrl.push({ body: createMockRunRecord({ run_id: "r1" }) });
    await useRunHistoryStore.getState().fetchRun("r1");

    const init = ctrl.mock.mock.calls[1][1] as RequestInit;
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBeNull();
  });

  it("HTTP 404 returns null without polluting cache", async () => {
    ctrl.push({ status: 404 });
    const result = await useRunHistoryStore.getState().fetchRun("nonexistent");
    expect(result).toBeNull();
    // No cache entry created — next call won't send If-Modified-Since.
    ctrl.push({ status: 404 });
    await useRunHistoryStore.getState().fetchRun("nonexistent");
    const init = ctrl.mock.mock.calls[1][1] as RequestInit;
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get("If-Modified-Since")).toBeNull();
  });
});

function promiseMicrotask(fn: () => void): void {
  Promise.resolve().then(fn);
}

// Suppress unused-import warning for createMockRunSummary — kept for
// potential per-test overrides in future test additions.
void createMockRunSummary;
