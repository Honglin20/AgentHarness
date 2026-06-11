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

describe("createConversationStore — iteration stamping", () => {
  it("addAgentMessage stamps iteration from currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    store.getState().addAgentMessage("coder", "coder");
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(2);
  });

  it("addAgentMessage stamps iteration=1 when no iteration set (legacy/default)", () => {
    const store = createConversationStore("wf-1");
    store.getState().addAgentMessage("coder", "coder");
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(1);
  });

  it("addToolCall stamps iteration from currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 3);
    store.getState().addToolCall("coder", "coder", "bash", { cmd: "ls" });
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(3);
  });

  it("addUserQuestion stamps iteration when node_id present", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    store.getState().addUserQuestion({
      question_id: "q1",
      agent_name: "coder",
      node_id: "coder",
      question: "Continue?",
    } as any);
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(2);
  });
});
