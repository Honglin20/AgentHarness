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
vi.mock("@/stores/appView", () => ({
  useAppViewStore: {
    getState: () => ({ setView: setViewSpy, setRunMode: setRunModeSpy }),
  },
}));

const showReplaySpy = vi.fn();
vi.mock("@/stores/viewStore", () => ({
  useViewStore: {
    getState: () => ({ showReplay: showReplaySpy }),
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

const { hydrateStoresSpy } = vi.hoisted(() => ({
  hydrateStoresSpy: vi.fn(),
}));
vi.mock("@/stores/hydration/hydrateReplay", () => ({
  hydrateStores: hydrateStoresSpy,
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
    showReplaySpy.mockClear();
    setWorkflowSpy.mockClear();
    fetchRunSpy.mockReset();
    hydrateStoresSpy.mockClear();
    hydrateStoresSpy.mockImplementation(async (run: RunRecord) => run);
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

  it("hydrates a running run via hydrateStores (scoped pipeline) + global setWorkflow + runMode live", async () => {
    const running = makeRun({
      status: "running",
      dag: { nodes: ["a"], edges: [] },
    });
    fetchRunSpy.mockResolvedValueOnce(running);

    await activateRun("r1");

    // Global workflowStore gets populated (page.tsx workflowId detection)
    expect(setWorkflowSpy).toHaveBeenCalledTimes(1);
    expect(setWorkflowSpy).toHaveBeenCalledWith("r1", "test-wf", running.dag);
    // hydrateStores called with the full run record (fills scoped stores
    // with events/conversation/agents that WS won't replay)
    expect(hydrateStoresSpy).toHaveBeenCalledTimes(1);
    expect(hydrateStoresSpy).toHaveBeenCalledWith(running, expect.any(Number), expect.any(Function));
    // showReplay NOT called for live runs (would clobber live UX)
    expect(showReplaySpy).not.toHaveBeenCalled();
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrated");
    expect(setRunModeSpy).toHaveBeenLastCalledWith("live");
  });

  it("does not set hydration=hydrated before hydrateStores resolves (running branch)", async () => {
    const running = makeRun({ status: "running", dag: { nodes: ["a"], edges: [] } });
    fetchRunSpy.mockResolvedValueOnce(running);

    let resolveHydrate: (r: RunRecord) => void = () => {};
    hydrateStoresSpy.mockReturnValueOnce(
      new Promise<RunRecord>((r) => {
        resolveHydrate = r;
      }),
    );

    const pending = activateRun("r1");
    // While hydrateStores is pending, hydration should still be "hydrating"
    expect(setHydrationSpy).toHaveBeenLastCalledWith("r1", "hydrating");
    expect(setHydrationSpy).not.toHaveBeenCalledWith("r1", "hydrated");

    resolveHydrate(running);
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
