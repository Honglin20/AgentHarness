import { describe, it, expect } from "vitest";
import { deriveOutlineItems } from "../deriveOutlineItems";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { NodeState } from "@/stores/workflowStore";
import type { TodoStep } from "@/contexts/workflow-context/stores/todo";

function msg(partial: Partial<ConversationMessage> & { id: string }): ConversationMessage {
  return {
    type: "agent",
    content: "",
    timestamp: 0,
    ...partial,
  } as ConversationMessage;
}

function node(partial: Partial<NodeState> & { id: string; name: string }): NodeState {
  return {
    status: "idle",
    ...partial,
  } as NodeState;
}

const emptyTodo: Record<string, TodoStep[]> = {};

describe("deriveOutlineItems", () => {
  it("returns empty array for empty inputs", () => {
    expect(deriveOutlineItems({}, [], emptyTodo)).toEqual([]);
  });

  it("emits one item per node, ordered by first-message timestamp", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "success", durationMs: 1000 }),
      b: node({ id: "b", name: "runner", status: "success", durationMs: 2000 }),
    };
    const messages = [
      msg({ id: "1", nodeId: "b", agentName: "runner", timestamp: 200, iteration: 1 }),
      msg({ id: "2", nodeId: "a", agentName: "analyzer", timestamp: 100, iteration: 1 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.map((i) => i.nodeId)).toEqual(["a", "b"]);
    expect(items[0].order).toBeLessThan(items[1].order);
  });

  it("includes nodes with no messages (idle nodes from DAG)", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "idle" }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe("idle");
    expect(items[0].iteration).toBe(1);
    expect(items[0].hasMultipleIterations).toBe(false);
  });

  it("splits same-nodeId messages into multiple items when iteration > 1 (loop)", () => {
    const nodes = {
      coder: node({ id: "coder", name: "coder", status: "success" }),
    };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items).toHaveLength(2);
    expect(items[0].iteration).toBe(1);
    expect(items[1].iteration).toBe(2);
    expect(items[0].key).toBe("coder__iter1");
    expect(items[1].key).toBe("coder__iter2");
    expect(items[0].hasMultipleIterations).toBe(true);
  });

  it("detects waiting-for-user status from pending question messages", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "running" }),
    };
    const messages = [
      msg({
        id: "1",
        nodeId: "a",
        agentName: "analyzer",
        timestamp: 100,
        iteration: 1,
        type: "question",
        status: "pending",
        questionId: "q1",
      } as any),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items[0].status).toBe("waiting-for-user");
    expect(items[0].activity).toMatchObject({ kind: "waiting-for-user", questionCount: 1 });
  });

  it("renders running status with current step from todos", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "running" }),
    };
    const todos = {
      a: [
        { taskId: "s1", content: "explore files", activeForm: "exploring files", status: "in_progress", detail: null },
        { taskId: "s2", content: "summarize", activeForm: "summarizing", status: "pending", detail: null },
      ] as TodoStep[],
    };
    const items = deriveOutlineItems(nodes, [], todos);
    expect(items[0].status).toBe("running");
    expect(items[0].activity).toMatchObject({ kind: "running", currentStepContent: "exploring files" });
  });

  it("retryAttempts produce a retry badge", () => {
    const nodes = {
      a: node({
        id: "a",
        name: "analyzer",
        status: "retrying",
        retryAttempts: [
          { attempt: 1, maxAttempts: 3, category: "NetworkError", reason: "timeout", delayS: 2, retryAfterS: null, ts: 0 },
        ],
      }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    expect(items[0].status).toBe("retrying");
    const retryBadge = items[0].badges.find((b) => b.kind === "retry");
    expect(retryBadge?.text).toBe("1/3");
  });

  it("tokens badge appears when total > 0", () => {
    const nodes = {
      a: node({
        id: "a",
        name: "analyzer",
        status: "success",
        tokenUsage: { input: 1000, output: 500, total: 1500 },
      }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    const tokBadge = items[0].badges.find((b) => b.kind === "tokens");
    expect(tokBadge?.text).toBe("1.5k");
  });

  it("legacy messages without iteration field are treated as iteration 1", () => {
    const nodes = { a: node({ id: "a", name: "a", status: "success" }) };
    const messages = [msg({ id: "1", nodeId: "a", agentName: "a", timestamp: 100 /* no iteration */ })];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items).toHaveLength(1);
    expect(items[0].iteration).toBe(1);
  });
});
