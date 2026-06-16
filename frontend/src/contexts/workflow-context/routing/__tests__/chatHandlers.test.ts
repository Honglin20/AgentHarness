/**
 * Tests for chat.answer / chat.timeout handlers — refresh correctness.
 *
 * Scenario: ask_user emits chat.question (critical, replayed on WS reconnect)
 * then chat.answer when the user picks. Without these handlers, a page
 * refresh during a question re-renders chat.question and the user is
 * prompted again. With them, the replayed chat.answer marks the question
 * answered, so the UI shows the resolved state instead of re-prompting.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import type { WorkflowStores } from "@/contexts/workflow-context/types";
import type { WSEvent } from "@/types/events";

function makeStoresWithQuestion(questionId: string, status: "pending" | "answered" | "timeout" = "pending") {
  const messages: any[] = [
    {
      id: "msg-q",
      type: "question",
      questionId,
      status,
      content: "Pick a model",
      timestamp: Date.now(),
    },
  ];

  // zustand-style: actions live on the state object returned by getState().
  // We attach the spies to BOTH the state object (for handler calls) and
  // to `conversation` (for test assertions) so test bodies can read either.
  const answerUserQuestion = vi.fn((qid: string, answer: any) => {
    const idx = messages.findIndex((m) => m.questionId === qid && m.status === "pending");
    if (idx !== -1) messages[idx] = { ...messages[idx], status: "answered", questionAnswer: answer };
  });
  const markQuestionTimeout = vi.fn((qid: string) => {
    const idx = messages.findIndex((m) => m.questionId === qid && m.status === "pending");
    if (idx !== -1) messages[idx] = { ...messages[idx], status: "timeout" };
  });
  const clearPendingQuestion = vi.fn((_qid: string) => { /* no-op */ });

  const state: any = {
    messages,
    pendingQuestionId: status === "pending" ? questionId : null,
    answerUserQuestion,
    markQuestionTimeout,
    clearPendingQuestion,
  };
  // conversation IS the state (zustand pattern), plus the store API methods.
  const conversation: any = {
    ...state,
    getState: () => state,
    setState: vi.fn(),
    subscribe: vi.fn(),
    getInitialState: vi.fn(),
  };
  const noopStore: any = {
    getState: () => ({}),
    setState: vi.fn(),
    subscribe: vi.fn(),
    getInitialState: vi.fn(),
  };
  return {
    stores: {
      conversation,
      workflow: noopStore,
      toolCall: noopStore,
      output: noopStore,
      chart: noopStore,
      todo: noopStore,
      span: noopStore,
      agentIO: noopStore,
      runHistory: noopStore,
    } as unknown as WorkflowStores,
    conversation,
    answerUserQuestion,
    markQuestionTimeout,
    clearPendingQuestion,
    getMessages: () => messages,
  };
}

function makeEvent<T extends string>(type: T, payload: any, seq = 1): WSEvent {
  return { type, ts: Date.now(), seq, payload } as WSEvent;
}

function makeCtx() {
  let n = 0;
  return { mode: "live" as const, persistence: null, counter: { next: () => `id-${++n}` } };
}

describe("chat.answer handler", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("marks pending question as answered with structured payload", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation, getMessages } = makeStoresWithQuestion("qid-1");

    routeEvent(
      stores,
      makeEvent("chat.answer", {
        workflow_id: "wf-x",
        question_id: "qid-1",
        answer: "Sonnet 4.6",
        raw: { selected: ["sonnet"], custom_input: "" },
      }),
      makeCtx(),
    );

    expect(conversation.answerUserQuestion).toHaveBeenCalledWith(
      "qid-1",
      { selected: ["sonnet"], customInput: "" },
    );
    expect(conversation.clearPendingQuestion).toHaveBeenCalledWith("qid-1");
    expect(getMessages()[0].status).toBe("answered");
  });

  it("falls back to customInput when raw is legacy {answer} shape", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation } = makeStoresWithQuestion("qid-2");

    routeEvent(
      stores,
      makeEvent("chat.answer", {
        question_id: "qid-2",
        answer: "free text",
        raw: { answer: "free text" },
      }),
      makeCtx(),
    );

    expect(conversation.answerUserQuestion).toHaveBeenCalledWith(
      "qid-2",
      { selected: [], customInput: "free text" },
    );
  });

  it("falls back to customInput when raw is missing entirely", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation } = makeStoresWithQuestion("qid-3");

    routeEvent(
      stores,
      makeEvent("chat.answer", {
        question_id: "qid-3",
        answer: "Sonnet",
      }),
      makeCtx(),
    );

    expect(conversation.answerUserQuestion).toHaveBeenCalledWith(
      "qid-3",
      { selected: [], customInput: "Sonnet" },
    );
  });

  it("is idempotent — second answer does not re-mark", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation } = makeStoresWithQuestion("qid-4", "answered");

    routeEvent(
      stores,
      makeEvent("chat.answer", {
        question_id: "qid-4",
        answer: "X",
        raw: { selected: [], custom_input: "" },
      }),
      makeCtx(),
    );

    expect(conversation.answerUserQuestion).not.toHaveBeenCalled();
  });

  it("silently drops answer for unknown question_id (no spurious store write)", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation } = makeStoresWithQuestion("qid-real");

    routeEvent(
      stores,
      makeEvent("chat.answer", {
        question_id: "qid-unknown",
        answer: "X",
      }),
      makeCtx(),
    );

    expect(conversation.answerUserQuestion).not.toHaveBeenCalled();
    expect(conversation.clearPendingQuestion).not.toHaveBeenCalled();
  });
});

describe("chat.timeout handler", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("marks pending question as timeout", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation, getMessages } = makeStoresWithQuestion("qid-t1");

    routeEvent(
      stores,
      makeEvent("chat.timeout", {
        question_id: "qid-t1",
        timeout_sec: 60,
      }),
      makeCtx(),
    );

    expect(conversation.markQuestionTimeout).toHaveBeenCalledWith("qid-t1");
    expect(conversation.clearPendingQuestion).toHaveBeenCalledWith("qid-t1");
    expect(getMessages()[0].status).toBe("timeout");
  });

  it("is idempotent — already-finalized question is untouched", async () => {
    const { routeEvent } = await import("../index");
    const { stores, conversation } = makeStoresWithQuestion("qid-t2", "answered");

    routeEvent(
      stores,
      makeEvent("chat.timeout", { question_id: "qid-t2" }),
      makeCtx(),
    );

    expect(conversation.markQuestionTimeout).not.toHaveBeenCalled();
  });
});

describe("refresh replay ordering — chat.question then chat.answer", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("replayed question+answer leaves the question answered (not re-prompted)", async () => {
    const { routeEvent } = await import("../index");

    // Simulate a fresh store: no messages yet (page was just refreshed)
    const messages: any[] = [];
    const addUserQuestion = vi.fn((p: any) => {
      messages.push({
        id: `msg-${messages.length + 1}`,
        type: "question",
        questionId: p.question_id,
        status: "pending",
        content: p.question,
        timestamp: Date.now(),
      });
    });
    const answerUserQuestion = vi.fn((qid: string, answer: any) => {
      const idx = messages.findIndex((m) => m.questionId === qid && m.status === "pending");
      if (idx !== -1) messages[idx] = { ...messages[idx], status: "answered", questionAnswer: answer };
    });
    const markQuestionTimeout = vi.fn();
    const clearPendingQuestion = vi.fn();

    const state: any = {
      messages,
      pendingQuestionId: null,
      addUserQuestion,
      answerUserQuestion,
      markQuestionTimeout,
      clearPendingQuestion,
    };
    const conversation: any = {
      getState: () => state,
      setState: vi.fn(),
      subscribe: vi.fn(),
      getInitialState: vi.fn(),
    };
    const noopStore: any = {
      getState: () => ({}),
      setState: vi.fn(),
      subscribe: vi.fn(),
      getInitialState: vi.fn(),
    };
    const stores = {
      conversation,
      workflow: noopStore,
      toolCall: noopStore,
      output: noopStore,
      chart: noopStore,
      todo: noopStore,
      span: noopStore,
      agentIO: noopStore,
      runHistory: noopStore,
    } as unknown as WorkflowStores;

    // Replay in seq order: question first, answer second
    routeEvent(
      stores,
      makeEvent("chat.question", {
        workflow_id: "wf-x",
        question_id: "qid-replay",
        question: "Pick a model",
        options: [{ label: "A", value: "a" }],
        multi_select: false,
        allow_custom_input: true,
        input_type: "text",
      }, 1),
      makeCtx(),
    );
    routeEvent(
      stores,
      makeEvent("chat.answer", {
        workflow_id: "wf-x",
        question_id: "qid-replay",
        answer: "A",
        raw: { selected: ["a"], custom_input: "" },
      }, 2),
      makeCtx(),
    );

    expect(addUserQuestion).toHaveBeenCalledTimes(1);
    expect(answerUserQuestion).toHaveBeenCalledWith(
      "qid-replay",
      { selected: ["a"], customInput: "" },
    );
    // Final state: question is answered, NOT still pending
    expect(messages[0].status).toBe("answered");
  });
});
