import { describe, it, expect } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";

describe("createConversationStore — iteration tracking", () => {
  it("initializes with empty currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    expect(store.getState().currentIterationByNode).toEqual({});
  });

  it("setCurrentIteration sets the iteration for a node", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    expect(store.getState().currentIterationByNode.coder).toBe(2);
  });

  it("setCurrentIteration is idempotent (same value → no-op)", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 1);
    const before = store.getState();
    store.getState().setCurrentIteration("coder", 1);
    expect(store.getState()).toBe(before);
  });

  it("reset() clears currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 3);
    store.getState().reset();
    expect(store.getState().currentIterationByNode).toEqual({});
  });
});
