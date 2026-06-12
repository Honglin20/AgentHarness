import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useAutoFollowSelection } from "../useAutoFollowSelection";
import { useOutlineStore } from "../outlineStore";
import type { OutlineItem } from "../types";

function runningItem(name: string, order: number): OutlineItem {
  return {
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "running",
    activity: { kind: "running", currentStepContent: "x" },
    badges: [],
    order,
  };
}

function waitingItem(name: string, questionId: string, order: number): OutlineItem {
  return {
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
    badges: [],
    order,
  };
}

describe("useAutoFollowSelection", () => {
  beforeEach(() => {
    // Reset the outline store between tests. zustand store is a singleton;
    // without reset, selection leaks across cases.
    useOutlineStore.setState({ autoFollow: true, selectedKey: null });
  });

  afterEach(() => {
    // Unmount all rendered hooks. Without this, multiple hook instances
    // stay mounted simultaneously — their effects share the singleton store
    // and race on selectedKey, producing flaky cross-test interference.
    cleanup();
  });

  it("autoFollow on + running item → selects it", () => {
    renderHook(() => useAutoFollowSelection([runningItem("analyzer", 0)]));
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });

  it("autoFollow on + waiting beats running", () => {
    renderHook(() =>
      useAutoFollowSelection([
        runningItem("runner", 10),
        waitingItem("analyzer", "q1", 0),
      ]),
    );
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });

  it("autoFollow on + multiple running → highest order wins", () => {
    renderHook(() =>
      useAutoFollowSelection([
        runningItem("early", 1),
        runningItem("late", 99),
      ]),
    );
    expect(useOutlineStore.getState().selectedKey).toBe("late__iter1");
  });

  it("autoFollow off → does not change selection", () => {
    useOutlineStore.setState({ autoFollow: false, selectedKey: "pinned__iter1" });
    renderHook(() => useAutoFollowSelection([runningItem("other", 0)]));
    expect(useOutlineStore.getState().selectedKey).toBe("pinned__iter1");
  });

  it("selection already correct → no spurious change", () => {
    useOutlineStore.setState({ autoFollow: true, selectedKey: "analyzer__iter1" });
    renderHook(() => useAutoFollowSelection([runningItem("analyzer", 0)]));
    expect(useOutlineStore.getState().selectedKey).toBe("analyzer__iter1");
  });
});
