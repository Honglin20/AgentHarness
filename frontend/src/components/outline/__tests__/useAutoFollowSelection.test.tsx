import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useAutoFollowSelection } from "../useAutoFollowSelection";
import { useOutlineStore } from "../outlineStore";
import type { OutlineGroup, OutlineItem } from "../types";

function makeGroup(
  nodeId: string,
  order: number,
  overrides: Partial<OutlineItem> = {},
): OutlineGroup {
  const latest: OutlineItem = {
    key: `${nodeId}__iter1`,
    nodeId,
    name: nodeId,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "idle",
    activity: { kind: "idle" },
    badges: [],
    order,
    ...overrides,
  };
  return {
    nodeId,
    name: nodeId,
    latest,
    iterCount: 1,
    latestIteration: 1,
    iters: [latest],
    order,
  };
}

function runningGroup(name: string, order: number): OutlineGroup {
  return makeGroup(name, order, {
    status: "running",
    activity: { kind: "running", currentStepContent: "x" },
  });
}

function waitingGroup(name: string, questionId: string, order: number): OutlineGroup {
  return makeGroup(name, order, {
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
  });
}

describe("useAutoFollowSelection", () => {
  beforeEach(() => {
    // Reset the outline store between tests. zustand store is a singleton;
    // without reset, selection leaks across cases.
    useOutlineStore.setState({ autoFollow: true, selectedNodeId: null, selectedIterByNode: {} });
  });

  afterEach(() => {
    // Unmount all rendered hooks. Without this, multiple hook instances
    // stay mounted simultaneously — their effects share the singleton store
    // and race on selectedNodeId, producing flaky cross-test interference.
    cleanup();
  });

  it("autoFollow on + running agent → selects it", () => {
    renderHook(() => useAutoFollowSelection([runningGroup("analyzer", 0)]));
    expect(useOutlineStore.getState().selectedNodeId).toBe("analyzer");
  });

  it("autoFollow on + waiting beats running", () => {
    renderHook(() =>
      useAutoFollowSelection([
        runningGroup("runner", 10),
        waitingGroup("analyzer", "q1", 0),
      ]),
    );
    expect(useOutlineStore.getState().selectedNodeId).toBe("analyzer");
  });

  it("autoFollow on + multiple running → highest order wins", () => {
    renderHook(() =>
      useAutoFollowSelection([
        runningGroup("early", 1),
        runningGroup("late", 99),
      ]),
    );
    expect(useOutlineStore.getState().selectedNodeId).toBe("late");
  });

  it("autoFollow off → does not change selection", () => {
    useOutlineStore.setState({ autoFollow: false, selectedNodeId: "pinned" });
    renderHook(() => useAutoFollowSelection([runningGroup("other", 0)]));
    expect(useOutlineStore.getState().selectedNodeId).toBe("pinned");
  });

  it("selection already correct → no spurious change", () => {
    useOutlineStore.setState({ autoFollow: true, selectedNodeId: "analyzer" });
    renderHook(() => useAutoFollowSelection([runningGroup("analyzer", 0)]));
    expect(useOutlineStore.getState().selectedNodeId).toBe("analyzer");
  });

  it("follows group.latest (multi-iter agent's latest status drives follow)", () => {
    // Two iters: iter 1 completed, iter 2 running. Group's latest = iter 2 running.
    const iter1: OutlineItem = {
      key: "x__iter1", nodeId: "x", name: "x", iteration: 1,
      hasMultipleIterations: true, isLatestIter: false,
      status: "completed", activity: { kind: "completed", durationMs: 1000 },
      badges: [], order: 0,
    };
    const iter2: OutlineItem = {
      key: "x__iter2", nodeId: "x", name: "x", iteration: 2,
      hasMultipleIterations: true, isLatestIter: true,
      status: "running", activity: { kind: "running", currentStepContent: "step" },
      badges: [], order: 1,
    };
    const group: OutlineGroup = {
      nodeId: "x", name: "x", latest: iter2,
      iterCount: 2, latestIteration: 2, iters: [iter1, iter2], order: 0,
    };
    renderHook(() => useAutoFollowSelection([group]));
    expect(useOutlineStore.getState().selectedNodeId).toBe("x");
  });
});
