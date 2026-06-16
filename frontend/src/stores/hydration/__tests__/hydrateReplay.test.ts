/**
 * Tests for the extracted hydration pipeline.
 *
 * The three stages (decideStrategy / loadSidecars / applyHydration) are
 * pure functions over (run, sidecars), so they test cleanly without
 * touching real scoped stores. applyHydration's writes are verified by
 * mocking the three downstream functions it can call.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { RunRecord } from "@/stores/runHistoryStore";
import {
  decideStrategy,
  loadSidecars,
  applyHydration,
  hydrateStores,
  type SidecarData,
} from "@/stores/hydration/hydrateReplay";

// Mock the three downstream hydration functions so applyHydration tests
// can assert which path was taken without standing up real scoped stores.
vi.mock("@/contexts/workflow-context/replayEvents", () => ({
  loadRunFromPersistedData: vi.fn(),
  loadLegacyRunData: vi.fn(),
  replayEventsToStores: vi.fn(),
}));

// Mock the run history store so loadSidecars can be tested without a real
// fetch implementation.
vi.mock("@/stores/runHistoryStore", () => ({
  useRunHistoryStore: {
    getState: () => ({
      fetchRunCharts: vi.fn().mockResolvedValue({ groups: {}, groupOrder: [] }),
      fetchRunEvents: vi.fn().mockResolvedValue([{ type: "node.started", ts: 0, payload: {} }]),
      fetchRunConversation: vi.fn().mockResolvedValue({
        messages: [{ id: "m1", type: "user", content: "hi" }],
        has_more: false,
        total: 1,
      }),
    }),
  },
}));

import { loadRunFromPersistedData, loadLegacyRunData, replayEventsToStores } from "@/contexts/workflow-context/replayEvents";

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

const emptySidecars: SidecarData = {
  charts: null,
  events: undefined,
  conversation: null,
  outline: null,
};

describe("decideStrategy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 'persisted' when agent_io + conversation + dag + trace all present", () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      conversation: [{ id: "m1", type: "user", content: "hi" }],
      dag: { nodes: ["writer"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [{ agent_name: "writer", status: "success", duration_ms: 100, error: null }],
      },
    });
    expect(decideStrategy(run, emptySidecars)).toBe("persisted");
  });

  it("returns 'persisted' when conversation comes from sidecar", () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      dag: { nodes: ["writer"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [{ agent_name: "writer", status: "success", duration_ms: 100, error: null }],
      },
    });
    const sidecars: SidecarData = {
      charts: null,
      events: undefined,
      conversation: { messages: [{ id: "m1", type: "user", content: "hi" }], has_more: false, total: 1 },
      outline: null,
    };
    expect(decideStrategy(run, sidecars)).toBe("persisted");
  });

  it("returns 'events' when persisted data is incomplete but events are present", () => {
    const run = makeRun({
      // missing dag, so persisted path can't apply
      dag: null,
    });
    const sidecars: SidecarData = {
      charts: null,
      events: [{ type: "node.started", ts: 0, payload: {} }] as any,
      conversation: null,
      outline: null,
    };
    expect(decideStrategy(run, sidecars)).toBe("events");
  });

  it("returns 'events' when agent_io is missing but events are present", () => {
    const run = makeRun({
      dag: { nodes: ["x"], edges: [] },
      conversation: [{ id: "m1", type: "user", content: "hi" }],
      // missing agent_io
    });
    const sidecars: SidecarData = {
      charts: null,
      events: [{ type: "node.started", ts: 0, payload: {} }] as any,
      conversation: null,
      outline: null,
    };
    expect(decideStrategy(run, sidecars)).toBe("events");
  });

  it("returns 'legacy' when nothing is present", () => {
    const run = makeRun();
    expect(decideStrategy(run, emptySidecars)).toBe("legacy");
  });

  it("returns 'legacy' when only some persisted fields are present", () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      // missing dag, conversation, trace
    });
    expect(decideStrategy(run, emptySidecars)).toBe("legacy");
  });
});

describe("loadSidecars", () => {
  it("returns inline data without fetching when _has_* flags are false", async () => {
    const run = makeRun({
      chart_groups: {
        groups: { g1: { label: "g1", collapsed: false, charts: {}, table: null } },
        groupOrder: ["g1"],
      },
      events: [{ type: "node.started", ts: 0, payload: {} }],
      conversation: [{ id: "m1", type: "user", content: "hi" }],
    });
    const result = await loadSidecars(run);
    expect(result.charts).toEqual(run.chart_groups);
    expect(result.events).toEqual(run.events);
    expect(result.conversation).toEqual({
      messages: run.conversation,
      has_more: false,
      total: run.conversation!.length,
    });
  });

  it("fetches conversation when _has_conversation is true and conversation is empty", async () => {
    const run = makeRun({ _has_conversation: true, conversation: [] });
    const result = await loadSidecars(run);
    expect(result.conversation).toEqual({
      messages: [{ id: "m1", type: "user", content: "hi" }],
      has_more: false,
      total: 1,
    });
  });

  it("fetches charts when _has_charts is true and chart_groups is null", async () => {
    const run = makeRun({ _has_charts: true, chart_groups: null });
    const result = await loadSidecars(run);
    expect(result.charts).toEqual({ groups: {}, groupOrder: [] });
  });

  it("fetches events when _has_events is true and events is undefined", async () => {
    const run = makeRun({ _has_events: true });
    const result = await loadSidecars(run);
    expect(result.events).toEqual([{ type: "node.started", ts: 0, payload: {} }]);
  });
});

describe("applyHydration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls loadRunFromPersistedData for 'persisted' strategy", () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      conversation: [{ id: "m1", type: "user", content: "hi" }],
      dag: { nodes: ["writer"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [{ agent_name: "writer", status: "success", duration_ms: 100, error: null }],
      },
    });
    const sidecars: SidecarData = { charts: null, events: undefined, conversation: null, outline: null };

    applyHydration("r1", run, sidecars, "persisted");

    expect(loadRunFromPersistedData).toHaveBeenCalledTimes(1);
    expect(loadLegacyRunData).not.toHaveBeenCalled();
    expect(replayEventsToStores).not.toHaveBeenCalled();
  });

  it("calls replayEventsToStores for 'events' strategy", () => {
    const run = makeRun();
    const sidecars: SidecarData = {
      charts: null,
      events: [{ type: "node.started", ts: 0, payload: {} }] as any,
      conversation: null,
      outline: null,
    };

    applyHydration("r1", run, sidecars, "events");

    expect(replayEventsToStores).toHaveBeenCalledTimes(1);
    expect(loadRunFromPersistedData).not.toHaveBeenCalled();
    expect(loadLegacyRunData).not.toHaveBeenCalled();
  });

  it("calls loadLegacyRunData for 'legacy' strategy", () => {
    const run = makeRun();
    applyHydration("r1", run, emptySidecars, "legacy");

    expect(loadLegacyRunData).toHaveBeenCalledTimes(1);
    expect(loadRunFromPersistedData).not.toHaveBeenCalled();
    expect(replayEventsToStores).not.toHaveBeenCalled();
  });

  it("falls back to legacy when 'events' strategy has empty events", () => {
    const run = makeRun();
    const sidecars: SidecarData = { charts: null, events: undefined, conversation: null, outline: null };

    // Should not happen via decideStrategy, but be defensive.
    applyHydration("r1", run, sidecars, "events");

    expect(loadLegacyRunData).toHaveBeenCalledTimes(1);
    expect(replayEventsToStores).not.toHaveBeenCalled();
  });

  it("returns merged run with sidecars applied", () => {
    const run = makeRun();
    const sidecars: SidecarData = {
      charts: { groups: {}, groupOrder: [] },
      events: [{ type: "x", ts: 0, payload: {} }] as any,
      conversation: {
        messages: [{ id: "m1", type: "user", content: "hi" }],
        has_more: false,
        total: 1,
      },
      outline: null,
    };

    const merged = applyHydration("r1", run, sidecars, "legacy");
    expect(merged.chart_groups).toEqual(sidecars.charts);
    expect(merged.events).toEqual(sidecars.events);
    expect(merged.conversation).toEqual(sidecars.conversation?.messages);
  });
});

describe("hydrateStores", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("applies hydration via the loadSidecars → decideStrategy → applyHydration pipeline", async () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      conversation: [{ id: "m1", type: "user", content: "hi" }],
      dag: { nodes: ["writer"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [{ agent_name: "writer", status: "success", duration_ms: 100, error: null }],
      },
    });

    let seq = 1;
    const merged = await hydrateStores(run, seq, () => seq);

    expect(loadRunFromPersistedData).toHaveBeenCalledTimes(1);
    // Merged record reflects sidecar application (chart_groups mirrored)
    expect(merged.run_id).toBe("r1");
  });

  it("bails (no applyHydration) when a newer call supersedes via getCurrentSeq", async () => {
    const run = makeRun({
      agent_io: { writer: { input_prompt: "x", output_result: "y" } },
      conversation: [{ id: "m1", type: "user", content: "hi" }],
      dag: { nodes: ["writer"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [{ agent_name: "writer", status: "success", duration_ms: 100, error: null }],
      },
    });

    // Caller passed seq=1, but getCurrentSeq now returns 2 — superseded.
    const merged = await hydrateStores(run, 1, () => 2);

    expect(loadRunFromPersistedData).not.toHaveBeenCalled();
    // Returns the original run untouched (no merge applied)
    expect(merged).toBe(run);
  });
});
