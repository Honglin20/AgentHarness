/**
 * Tests for activateRun — the single entry point for run activation.
 *
 * Mocks the stores + WorkflowManager so we can assert on hydration state
 * transitions and which hydration path was taken, without standing up
 * real scoped stores or hitting the network.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { RunRecord } from "@/stores/runHistoryStore";

// ── Module-level spies (single instance per test, survives across
//    getWorkflowManager() calls so call counts accumulate correctly). ────

const entries = new Map<string, { hydration: string }>();
const listeners = new Set<() => void>();

const getOrCreateSpy = vi.fn((id: string) => {
  if (!entries.has(id)) entries.set(id, { hydration: "idle" });
  return { stores: { workflow: { getState: () => ({ setWorkflow: setWorkflowSpy }) } } };
});
const getHydrationSpy = vi.fn((id: string) => entries.get(id)?.hydration ?? "idle");
const setHydrationSpy = vi.fn((id: string, h: string) => {
  const e = entries.get(id);
  if (!e) return;
  e.hydration = h;
  listeners.forEach((l) => l());
});
const subscribeToHydrationSpy = vi.fn((l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
});

vi.mock("@/contexts/workflow-context/WorkflowManager", () => ({
  getWorkflowManager: () => ({
    getOrCreate: getOrCreateSpy,
    getHydration: getHydrationSpy,
    setHydration: setHydrationSpy,
    subscribeToHydration: subscribeToHydrationSpy,
  }),
}));

const setViewSpy = vi.fn();
const setRunModeSpy = vi.fn();
const setWsSinceSeqSpy = vi.fn();
vi.mock("@/stores/appView", () => ({
  useAppViewStore: {
    getState: () => ({
      setView: setViewSpy,
      setRunMode: setRunModeSpy,
      setWsSinceSeq: setWsSinceSeqSpy,
    }),
  },
}));

const showReplaySpy = vi.fn();
const showLiveSpy = vi.fn();
vi.mock("@/stores/viewStore", () => ({
  useViewStore: {
    getState: () => ({ showReplay: showReplaySpy, showLive: showLiveSpy }),
  },
}));

const setWorkflowSpy = vi.fn();
vi.mock("@/stores/workflowStore", () => ({
  useWorkflowStore: {
    getState: () => ({ setWorkflow: setWorkflowSpy }),
  },
}));

const fetchRunSpy = vi.fn();
vi.mock("@/stores/runHistoryStore", () => ({
  useRunHistoryStore: {
    getState: () => ({ fetchRun: fetchRunSpy }),
  },
}));

const { hydrateStoresSpy, hydratePhase1Spy, hydrateFromSnapshotSpy, fetchSnapshotSpy, hydrateOutlineSidecarSpy, setHydratedCursorSpy } = vi.hoisted(() => ({
  hydrateStoresSpy: vi.fn(),
  hydratePhase1Spy: vi.fn(),
  hydrateFromSnapshotSpy: vi.fn(),
  // Default to null (legacy run / no snapshot) so existing phase 1 tests
  // keep their semantics. Tests that exercise the snapshot path override.
  fetchSnapshotSpy: vi.fn().mockResolvedValue(null),
  hydrateOutlineSidecarSpy: vi.fn().mockResolvedValue(undefined),
  setHydratedCursorSpy: vi.fn(),
}));
vi.mock("@/stores/hydration/hydrateReplay", () => ({
  hydrateStores: hydrateStoresSpy,
  hydratePhase1: hydratePhase1Spy,
  hydrateFromSnapshot: hydrateFromSnapshotSpy,
  fetchSnapshot: fetchSnapshotSpy,
  hydrateOutlineSidecar: hydrateOutlineSidecarSpy,
}));

vi.mock("@/contexts/workflow-context/routing", () => ({
  setHydratedCursor: setHydratedCursorSpy,
}));

// Import AFTER mocks are declared.
import { activateRun, _resetActivateRunStateForTests } from "@/lib/activateRun";

function makeRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: "r1",
    workflow_name: "test-wf",
    agents_snapshot: [],
    status: "completed",
    inputs: {},
    result: null,
    conversation: [],
    created_at: new Date("2026-06-01").toISOString(),
    dag: null,
    chart_groups: null,
    ...overrides,
  };
}

describe("activateRun", () => {
  beforeEach(() => {
    setViewSpy.mockClear();
    setRunModeSpy.mockClear();
    setWsSinceSeqSpy.mockClear();
    showReplaySpy.mockClear();
    showLiveSpy.mockClear();
    setWorkflowSpy.mockClear();
    fetchRunSpy.mockReset();
    hydrateStoresSpy.mockClear();
    hydrateStoresSpy.mockImplementation(async (run: RunRecord) => run);
    hydratePhase1Spy.mockReset();
    hydratePhase1Spy.mockResolvedValue(undefined);
    hydrateFromSnapshotSpy.mockReset();
    fetchSnapshotSpy.mockReset();
    // Default: no snapshot available → activateRun falls back to phase 1.
    fetchSnapshotSpy.mockResolvedValue(null);
    setHydratedCursorSpy.mockClear();
    getOrCreateSpy.mockClear();
    getHydrationSpy.mockClear();
    setHydrationSpy.mockClear();
    subscribeToHydrationSpy.mockClear();
    entries.clear();
    listeners.clear();
    _resetActivateRunStateForTests();
  });

  it("hydrates a completed run via showReplay + sets hydration to hydrated", async () => {
    const completed = makeRun({ status: "completed" });
    fetchRunSpy.mockResolvedValueOnce(completed);

    await activateRun("r1");

    expect(setHydrationSpy).toHaveBeenCalledWith("r1", "hydrating");
    expect(showReplaySpy).toHaveBeenCalledWith(completed);
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrated");
    expect(setWorkflowSpy).not.toHaveBeenCalled();
  });

  it("hydrates a running run via phase 1 only (WS replays events for phase 2)", async () => {
    const running = makeRun({
      status: "running",
      dag: { nodes: ["a"], edges: [] },
    });
    fetchRunSpy.mockResolvedValueOnce(running);

    await activateRun("r1");

    // Global workflowStore gets populated (page.tsx workflowId detection)
    expect(setWorkflowSpy).toHaveBeenCalledTimes(1);
    expect(setWorkflowSpy).toHaveBeenCalledWith("r1", "test-wf", running.dag);
    // Phase 1 awaited (workflow store + outline sidecar) — fallback path
    // (fetchSnapshot returned null, treating this as a legacy run).
    expect(hydratePhase1Spy).toHaveBeenCalledTimes(1);
    expect(hydratePhase1Spy).toHaveBeenCalledWith(running);
    // Phase 2 (hydrateStores) NOT called — WS sinceSeq=0 replays all
    // buffered events into scoped stores, and hydrateStores' internal
    // resetAllStores would race the WS stream (review #2 finding).
    expect(hydrateStoresSpy).not.toHaveBeenCalled();
    // showReplay NOT called for live runs (would clobber live UX)
    expect(showReplaySpy).not.toHaveBeenCalled();
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrated");
    expect(setRunModeSpy).toHaveBeenLastCalledWith("live");
    // Bug #5 fix: showLive is invoked before setWorkflow so useViewStore
    // doesn't keep pointing at a prior replay runId.
    expect(showLiveSpy).toHaveBeenCalledTimes(1);
    // WS cursor stays at 0 (no snapshot) so full replay runs.
    expect(setWsSinceSeqSpy).toHaveBeenCalledWith(0);
  });

  it("hydrates a running run via snapshot when available (Phase 1 long-run replay)", async () => {
    const running = makeRun({
      status: "running",
      dag: { nodes: ["a"], edges: [] },
    });
    fetchRunSpy.mockResolvedValueOnce(running);
    const snapshot = {
      run_id: "r1",
      workflow_name: "test-wf",
      status: "running",
      seq_cursor: 1234,
      dag: { nodes: ["a"], edges: [] },
      conversation: [],
      charts: null,
      todo_states: null,
    };
    fetchSnapshotSpy.mockResolvedValueOnce(snapshot);

    await activateRun("r1");

    // Snapshot path taken — single-pass hydrate replaces phase 1.
    expect(hydrateFromSnapshotSpy).toHaveBeenCalledTimes(1);
    expect(hydrateFromSnapshotSpy).toHaveBeenCalledWith(snapshot);
    expect(hydratePhase1Spy).not.toHaveBeenCalled();
    // Hydration watermark set so dedup drops any WS event with seq ≤ 1234
    expect(setHydratedCursorSpy).toHaveBeenCalledWith("r1", 1234);
    // WS connects with since_seq=1234 — only delivers post-snapshot events
    expect(setWsSinceSeqSpy).toHaveBeenCalledWith(1234);
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrated");
    expect(setRunModeSpy).toHaveBeenLastCalledWith("live");
  });

  it("does not set hydration=hydrated before phase 1 resolves (running branch)", async () => {
    const running = makeRun({ status: "running", dag: { nodes: ["a"], edges: [] } });
    fetchRunSpy.mockResolvedValueOnce(running);

    let resolvePhase1: () => void = () => {};
    hydratePhase1Spy.mockReturnValueOnce(
      new Promise<void>((r) => {
        resolvePhase1 = r;
      }),
    );

    const pending = activateRun("r1");
    // While phase 1 is pending, hydration should still be "hydrating"
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrating");
    expect(setHydrationSpy).not.toHaveBeenCalledWith("r1", "hydrated");

    resolvePhase1();
    await pending;

    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrated");
  });

  it("sets hydration to failed when fetchRun returns null", async () => {
    fetchRunSpy.mockResolvedValueOnce(null);

    await activateRun("r1");

    expect(setHydrationSpy).toHaveBeenCalledWith("r1", "failed");
    expect(showReplaySpy).not.toHaveBeenCalled();
    expect(setWorkflowSpy).not.toHaveBeenCalled();
  });

  it("sets hydration to failed when fetchRun throws", async () => {
    fetchRunSpy.mockRejectedValueOnce(new Error("network"));

    await activateRun("r1");

    expect(setHydrationSpy).toHaveBeenCalledWith("r1", "failed");
  });

  it("aborts prior in-flight fetch when called again (seq guard)", async () => {
    let resolveFirst: (v: RunRecord | null) => void = () => {};
    const firstPromise = new Promise<RunRecord | null>((r) => {
      resolveFirst = r;
    });
    fetchRunSpy.mockReturnValueOnce(firstPromise);
    fetchRunSpy.mockResolvedValueOnce(makeRun({ status: "completed" }));

    // Kick off first call but don't await yet
    const first = activateRun("r1");
    // Immediately fire second call — supersedes the first
    const second = activateRun("r2");

    // Resolve the first's fetch — should be ignored due to seq guard
    resolveFirst(null);
    await first;
    await second;

    // r2 should reach hydrated; r1's setHydration calls after the abort
    // are seq-guarded.
    const lastCall = setHydrationSpy.mock.calls.at(-1);
    expect(lastCall?.[0]).toBe("r2");
    expect(lastCall?.[1]).toBe("hydrated");
  });

  it("calls getOrCreate before any await (so WS events aren't dropped)", async () => {
    fetchRunSpy.mockResolvedValueOnce(makeRun({ status: "completed" }));

    await activateRun("r1");

    expect(getOrCreateSpy).toHaveBeenCalledWith("r1");
  });
});
