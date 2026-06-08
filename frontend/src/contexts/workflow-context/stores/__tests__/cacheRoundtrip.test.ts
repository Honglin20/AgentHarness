import { describe, expect, it } from "vitest";
import type {
  NodeCompletedPayload,
  NodeStartedPayload,
} from "@/types/events";
import { createWorkflowStore } from "@/contexts/workflow-context/stores/workflow";

describe("scoped workflow store cache round-trip", () => {
  it("updateNodeInCache preserves tokenBreakdown across setActiveWid round-trip", () => {
    // Simulate batch-mode background workflow: user is on wf-1, wf-2 runs in
    // background and its node.completed events route through updateNodeInCache.
    // When user later switches to wf-2 via setActiveWid, the cached snapshot
    // must still carry tokenBreakdown.
    const store = createWorkflowStore("wf-1");

    // Seed wf-1 as active so setActiveWid("wf-2") saves wf-1 first.
    store.getState().setActiveWid("wf-1");

    const started: NodeStartedPayload = {
      node_id: "node-a",
      agent_name: "writer",
      attempt: 1,
      tools: [],
      model: "test-model",
    };
    store.getState().updateNodeInCache("wf-2", started);

    const completed: NodeCompletedPayload = {
      node_id: "node-a",
      agent_name: "writer",
      duration_ms: 1234,
      status: "success",
      token_usage: { input: 100, output: 50, total: 150 },
      token_breakdown: {
        writer: { input: 100, output: 50, total: 150 },
        "writer.sub_agent": { input: 30, output: 10, total: 40 },
      },
      cost_usd: 0.0123,
      ttft_ms: 200,
    };
    store.getState().updateNodeInCache("wf-2", completed);

    // Switch active to wf-2 — this should apply the wf-2 cached snapshot.
    store.getState().setActiveWid("wf-2");

    const restored = store.getState().nodes["node-a"];
    expect(restored).toBeDefined();
    expect(restored.tokenBreakdown).toEqual({
      writer: { input: 100, output: 50, total: 150 },
      "writer.sub_agent": { input: 30, output: 10, total: 40 },
    });
    expect(restored.tokenUsage).toEqual({ input: 100, output: 50, total: 150 });
    expect(restored.costUsd).toBe(0.0123);
    expect(restored.ttftMs).toBe(200);
  });

  it("updateNodeInCache with NodeCompleted writes tokenBreakdown into the cached snapshot directly", () => {
    const store = createWorkflowStore("wf-3");
    store.getState().setActiveWid("wf-3");

    const completed: NodeCompletedPayload = {
      node_id: "node-x",
      agent_name: "planner",
      duration_ms: 500,
      status: "success",
      token_breakdown: {
        planner: { input: 50, output: 20, total: 70 },
      },
    };
    store.getState().updateNodeInCache("wf-3", completed);

    // The cached snapshot itself must carry tokenBreakdown — this is the
    // underlying invariant the round-trip test above relies on.
    const cache = store.getState()._cache;
    expect(cache["wf-3"]).toBeDefined();
    expect(cache["wf-3"].nodes["node-x"].tokenBreakdown).toEqual({
      planner: { input: 50, output: 20, total: 70 },
    });
  });
});
