/**
 * Tests for ask_user question lifecycle in the global conversation store.
 *
 * Focus: markAllPendingQuestionsInterrupted — called when the workflow
 * terminates so pending questions don't linger in a "select an option"
 * state that the user can no longer affect.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useConversationStore } from "@/stores/conversationStore";
import type { AgentQuestionPayload } from "@/stores/conversationStore";

function reset() {
  useConversationStore.setState({
    messages: [],
    pendingQuestionId: null,
    pendingQuestionAgent: null,
  });
}

function addPendingQuestion(qid: string, agent = "agent_a") {
  useConversationStore.getState().addUserQuestion({
    question_id: qid,
    question: `Q ${qid}`,
    agent_name: agent,
    node_id: `node_${qid}`,
    header: null,
    options: [{ label: "A", value: "a" }, { label: "B", value: "b" }],
    multi_select: false,
    allow_custom_input: false,
    input_type: "text",
    input_placeholder: null,
  } satisfies AgentQuestionPayload);
}

describe("markAllPendingQuestionsInterrupted", () => {
  beforeEach(reset);

  it("marks every pending question as interrupted", () => {
    addPendingQuestion("q1");
    addPendingQuestion("q2");
    addPendingQuestion("q3");

    useConversationStore.getState().markAllPendingQuestionsInterrupted();

    const msgs = useConversationStore.getState().messages;
    const questions = msgs.filter((m) => m.type === "question");
    expect(questions).toHaveLength(3);
    expect(questions.every((m) => m.status === "interrupted")).toBe(true);
  });

  it("leaves already-answered questions untouched", () => {
    addPendingQuestion("q1");
    addPendingQuestion("q2");

    // Answer q1 — should stay "answered" after the sweep
    useConversationStore.getState().answerUserQuestion("q1", {
      selected: ["a"],
      customInput: "",
    });

    useConversationStore.getState().markAllPendingQuestionsInterrupted();

    const msgs = useConversationStore.getState().messages;
    const q1 = msgs.find((m) => m.questionId === "q1");
    const q2 = msgs.find((m) => m.questionId === "q2");
    expect(q1?.status).toBe("answered");
    expect(q2?.status).toBe("interrupted");
  });

  it("clears pendingQuestionId pointer", () => {
    addPendingQuestion("q1");
    // v3 (ADR D5): addUserQuestion now sets pendingQuestionId directly.
    // No need to simulate the router — the store action itself sets the pointer.
    expect(useConversationStore.getState().pendingQuestionId).toBe("q1");

    useConversationStore.getState().markAllPendingQuestionsInterrupted();

    expect(useConversationStore.getState().pendingQuestionId).toBeNull();
    expect(useConversationStore.getState().pendingQuestionAgent).toBeNull();
  });

  it("v3 D5: addUserQuestion sets pendingQuestionId + pendingQuestionAgent", () => {
    // Regression for ADR single-source-streaming-state D5: addUserQuestion
    // previously only pushed the message — the derived pointer stayed null,
    // so usePendingQuestion() returned nothing on the live WS path.
    addPendingQuestion("q_xyz", "agent_selector");

    const state = useConversationStore.getState();
    expect(state.pendingQuestionId).toBe("q_xyz");
    expect(state.pendingQuestionAgent).toBe("agent_selector");

    // Message also carries the questionId (sanity check).
    const msg = state.messages.find((m) => m.type === "question");
    expect(msg?.questionId).toBe("q_xyz");
  });

  it("is a no-op on messages when there are no pending questions", () => {
    addPendingQuestion("q1");
    useConversationStore.getState().answerUserQuestion("q1", {
      selected: ["a"],
      customInput: "",
    });

    const before = useConversationStore.getState().messages;
    useConversationStore.getState().markAllPendingQuestionsInterrupted();
    const after = useConversationStore.getState().messages;

    // v3 D5: addUserQuestion now sets pendingQuestionId, so the action
    // DOES clear the pointer (no longer a pure no-op). But messages array
    // is unchanged — no question had status=pending anymore.
    expect(after).toEqual(before);
    expect(useConversationStore.getState().pendingQuestionId).toBeNull();
  });

  it("does not touch non-question messages", () => {
    useConversationStore.getState().addAgentMessage("node_x", "agent_a");
    addPendingQuestion("q1");
    useConversationStore.getState().addSystemMessage("hello");

    useConversationStore.getState().markAllPendingQuestionsInterrupted();

    const msgs = useConversationStore.getState().messages;
    const agent = msgs.find((m) => m.type === "agent");
    const sys = msgs.find((m) => m.type === "system");
    expect(agent).toBeDefined();
    expect(sys).toBeDefined();
    expect(sys?.content).toBe("hello");
  });
});
