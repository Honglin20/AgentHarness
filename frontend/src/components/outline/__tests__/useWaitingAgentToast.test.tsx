import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useWaitingAgentToast } from "../useWaitingAgentToast";
import type { OutlineGroup, OutlineItem } from "../types";

// Mock sonner.toast so we can assert on calls without spawning real toasts.
const toastInfo = vi.fn();
vi.mock("sonner", () => ({ toast: { info: (...args: unknown[]) => toastInfo(...args) } }));

function wrap(item: OutlineItem): OutlineGroup {
  return {
    nodeId: item.nodeId,
    name: item.name,
    latest: item,
    iterCount: 1,
    latestIteration: item.iteration,
    iters: [item],
    order: item.order,
  };
}

function waitingItem(name: string, questionId: string, iter: number = 1): OutlineGroup {
  return wrap({
    key: `${name}__iter${iter}`,
    nodeId: name,
    name,
    iteration: iter,
    hasMultipleIterations: iter > 1,
    isLatestIter: true,
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
    badges: [],
    order: 0,
  });
}

function idleItem(name: string): OutlineGroup {
  return wrap({
    key: `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "idle",
    activity: { kind: "idle" },
    badges: [],
    order: 0,
  });
}

// renderHelper re-renders the hook with successive items arrays.
function renderHelper() {
  return renderHook(
    ({ items }: { items: OutlineGroup[] }) => {
      useWaitingAgentToast(items);
    },
    { initialProps: { items: [] as OutlineGroup[] } },
  );
}

describe("useWaitingAgentToast", () => {
  beforeEach(() => {
    toastInfo.mockClear();
  });
  afterEach(() => {
    vi.clearAllMocks();
    // Unmount rendered hooks so each test starts fresh — without cleanup,
    // previously rendered hook instances keep their refs / effects alive
    // and can interfere with later tests' assertions.
    cleanup();
  });

  it("fires toast on first waiting item", () => {
    const r = renderHelper();
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(
      "analyzer is waiting for your answer",
      expect.objectContaining({ duration: 8000 }),
    );
  });

  it("Bug 2 fix — same agent, second question, still fires", () => {
    const r = renderHelper();
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // User answers → no waiting.
    r.rerender({ items: [idleItem("analyzer")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Same agent asks again with a new questionId → toast fires again.
    r.rerender({ items: [waitingItem("analyzer", "q2")] });
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });

  it("does NOT re-fire while same questionId persists", () => {
    const r = renderHelper();
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
  });

  it("switches to a different waiting agent → fires", () => {
    const r = renderHelper();
    r.rerender({ items: [waitingItem("analyzer", "q1")] });
    r.rerender({ items: [waitingItem("runner", "q2")] });
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });

  it("multi-waiting priority — earliest firstTs (first in array) wins", () => {
    const r = renderHelper();
    // deriveOutlineItems sorts by firstTs ascending; the first array entry
    // is the earliest-waiting. Two simultaneous waiting items → toast fires
    // for the first one's questionId.
    r.rerender({
      items: [
        waitingItem("analyzer", "q-early"),
        waitingItem("runner", "q-late"),
      ],
    });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(
      "analyzer is waiting for your answer",
      expect.anything(),
    );
  });

  it("fallback path — missing questionId degrades to iter-based identity", () => {
    const r = renderHelper();
    // Engine regression case: questionId unset on the question message.
    r.rerender({ items: [waitingItem("analyzer", "")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Same iter, empty questionId again → no re-fire.
    r.rerender({ items: [waitingItem("analyzer", "")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Iter bumped → fires again even though qid empty (fallback id includes
    // nodeId + latestIteration, so the new iter is a fresh identity).
    r.rerender({ items: [waitingItem("analyzer", "", 2)] });
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });
});
