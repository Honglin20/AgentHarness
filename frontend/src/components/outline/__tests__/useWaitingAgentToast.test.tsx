import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useWaitingAgentToast } from "../useWaitingAgentToast";
import type { OutlineItem } from "../types";

// Mock sonner.toast so we can assert on calls without spawning real toasts.
const toastInfo = vi.fn();
vi.mock("sonner", () => ({ toast: { info: (...args: unknown[]) => toastInfo(...args) } }));

function waitingItem(name: string, questionId: string, key?: string): OutlineItem {
  return {
    key: key ?? `${name}__iter1`,
    nodeId: name,
    name,
    iteration: 1,
    hasMultipleIterations: false,
    isLatestIter: true,
    status: "waiting-for-user",
    activity: { kind: "waiting-for-user", questionId, questionCount: 1 },
    badges: [],
    order: 0,
  };
}

function idleItem(name: string): OutlineItem {
  return {
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
  };
}

// renderHelper re-renders the hook with successive items arrays.
function renderHelper() {
  return renderHook(
    ({ items }: { items: OutlineItem[] }) => {
      useWaitingAgentToast(items);
    },
    { initialProps: { items: [] as OutlineItem[] } },
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
        waitingItem("analyzer", "q-early", "analyzer__iter1"),
        waitingItem("runner", "q-late", "runner__iter1"),
      ],
    });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(
      "analyzer is waiting for your answer",
      expect.anything(),
    );
  });

  it("fallback path — missing questionId degrades to key-based identity", () => {
    const r = renderHelper();
    // Engine regression case: questionId unset on the question message.
    r.rerender({ items: [waitingItem("analyzer", "", "analyzer__iter1")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Same key, empty questionId again → no re-fire.
    r.rerender({ items: [waitingItem("analyzer", "", "analyzer__iter1")] });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    // Different key (e.g. iter bumped) → fires again even though qid empty.
    r.rerender({ items: [waitingItem("analyzer", "", "analyzer__iter2")] });
    expect(toastInfo).toHaveBeenCalledTimes(2);
  });
});
