/**
 * Shared test utilities for frontend store / lib tests.
 *
 * Design:
 *  - No jsdom dependency — pure-node stores work without DOM.
 *  - Mocked `global.fetch` covers `fetchWithAuth` callers transparently.
 *  - Factory helpers produce realistic RunRecord shapes so tests don't
 *    manually fill 15+ required fields just to satisfy TypeScript.
 *  - Async helpers use real microtask scheduling (no fake timers) so the
 *    test code path matches production behaviour; use `vi.useFakeTimers`
 *    explicitly when a test specifically exercises TTL / polling.
 */

import { vi } from "vitest";
import type { RunRecord, RunSummary } from "@/stores/runHistoryStore";

// ---------------------------------------------------------------------------
// Mock fetch controller
// ---------------------------------------------------------------------------

export interface MockResponse {
  /** HTTP status (default 200). */
  status?: number;
  /** JSON body (will be passed through `Response.json()`). */
  body?: unknown;
  /** Response headers — e.g. `{ "Last-Modified": "..." }`. */
  headers?: Record<string, string>;
}

export interface MockFetchController {
  /** Underlying vitest mock — call `.mock.calls` to assert request count / headers. */
  mock: ReturnType<typeof vi.fn>;
  /** Restore the original `global.fetch`. Call in `afterEach`. */
  restore: () => void;
  /** Append a response to the queue without resetting the mock. */
  push: (response: MockResponse) => void;
  /** Current number of times `fetch` has been invoked. */
  callCount: () => number;
}

function makeResponse(r: MockResponse): Response {
  const status = r.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 304 ? "Not Modified" : "OK",
    json: async () => r.body,
    text: async () => (typeof r.body === "string" ? r.body : JSON.stringify(r.body)),
    headers: new Headers(r.headers ?? {}),
  } as Response;
}

/**
 * Replace `global.fetch` with a queue-backed mock. Each call pops the next
 * response from the queue; if the queue is empty, subsequent calls receive
 * a default `{ status: 200, body: {} }` so tests don't have to count
 * requests exactly when they don't care.
 *
 * The mocked `fetch` accepts `(url: string, init?: RequestInit)` — same
 * shape `fetchWithAuth` uses — and stores `(url, init)` tuples in
 * `mock.mock.calls[i]` for assertion.
 */
export function mockFetch(initial: MockResponse[] = []): MockFetchController {
  const queue = [...initial];
  const original = global.fetch;

  const mock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const r = queue.shift() ?? { status: 200, body: {} };
    void url;
    void init;
    return makeResponse(r);
  });

  global.fetch = mock as unknown as typeof global.fetch;

  return {
    mock,
    restore: () => {
      global.fetch = original;
    },
    push: (r) => queue.push(r),
    callCount: () => mock.mock.calls.length,
  };
}

// ---------------------------------------------------------------------------
// Run summary / record factories
// ---------------------------------------------------------------------------

let _runIdSeq = 0;

function nextRunId(prefix = "run"): string {
  _runIdSeq += 1;
  return `${prefix}-${_runIdSeq.toString(36).padStart(4, "0")}`;
}

/** Reset the auto-increment run id counter — call in `beforeEach` if tests
 *  depend on stable ids. */
export function resetRunIdCounter(): void {
  _runIdSeq = 0;
}

export function createMockRunSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: nextRunId(),
    workflow_name: "test-wf",
    status: "completed",
    inputs: { task: "test task" },
    created_at: new Date("2026-06-01T00:00:00.000Z").toISOString(),
    ...overrides,
  };
}

export function createMockRunRecord(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: nextRunId(),
    workflow_name: "test-wf",
    agents_snapshot: [],
    status: "completed",
    inputs: {},
    result: null,
    conversation: [],
    created_at: new Date("2026-06-01T00:00:00.000Z").toISOString(),
    dag: null,
    chart_groups: null,
    ...overrides,
  };
}

/** Build N run summaries with deterministic ids (`run-0001`...`run-000N`). */
export function createMockRunSummaries(n: number, overrides: Partial<RunSummary> = {}): RunSummary[] {
  return Array.from({ length: n }, () => createMockRunSummary(overrides));
}

// ---------------------------------------------------------------------------
// Async helpers
// ---------------------------------------------------------------------------

/**
 * Poll `fn` until it returns a truthy value or `timeoutMs` elapses.
 * Use to wait for an async store update that resolves after a mocked
 * `fetch` completes. Resolves with the first truthy return value.
 *
 * Predicate contract: return a truthy value to stop polling. Booleans,
 * non-zero numbers, non-empty arrays, and object references all qualify.
 * Falsy values (false, 0, "", null, undefined, NaN) keep polling.
 *
 * Uses real microtask scheduling — pair with `vi.useFakeTimers` only if
 * the test specifically needs to advance wall-clock time.
 */
export async function waitFor<T>(
  fn: () => T | undefined | null,
  timeoutMs = 1000,
  intervalMs = 10,
): Promise<NonNullable<T>> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const v = fn();
      if (v) return v as NonNullable<T>;
    } catch {
      // swallow — keep polling until predicate passes
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`waitFor timed out after ${timeoutMs}ms`);
}

/** Wait for the next microtask + macrotask flush. Use after triggering an
 *  async store action so its promise chain has a chance to settle. */
export async function flushAsync(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
}
