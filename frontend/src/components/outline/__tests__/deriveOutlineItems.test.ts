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

  it("retryAttempts produce a retry badge showing the upcoming attempt", () => {
    // RetryAttempt.attempt=1 means "attempt 1 just failed". The badge
    // displays the upcoming retry number (2), matching the toast at
    // agentHandlers.ts:148 and inline card at AgentMessage.tsx:388.
    // All three surfaces must agree — do not change one in isolation.
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
    expect(retryBadge?.text).toBe("2/3");
    expect(items[0].activity).toMatchObject({ kind: "retrying", attempt: 2, maxAttempts: 3 });
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

  it("skips synthetic followup-* nodeIds (they aren't real DAG nodes)", () => {
    // ChatInput creates `followup-${agentName}` entries for @mention
    // multi-turn convos. They never fire node.started, so they must NOT
    // appear as outline rows — otherwise users see phantom agents detached
    // from the original.
    const nodes = {
      analyzer: node({ id: "analyzer", name: "analyzer", status: "success" }),
    };
    const messages = [
      msg({ id: "1", nodeId: "analyzer", agentName: "analyzer", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "followup-analyzer", agentName: "analyzer", timestamp: 200, iteration: 1, type: "user" as any, followup: true }),
      msg({ id: "3", nodeId: "followup-analyzer", agentName: "analyzer", timestamp: 300, iteration: 1 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items).toHaveLength(1);
    expect(items[0].nodeId).toBe("analyzer");
    expect(items.find((i) => i.nodeId.startsWith("followup-"))).toBeUndefined();
  });

  // ── Plan E: iter isolation + badge degradation ─────────────────────────

  it("filters todos by iteration in computeActivity (Bug 3 fix)", () => {
    // Without iter filtering, iter=2's "running" activity would pick up
    // iter=1's in_progress step (s1) and show the wrong "current step".
    const nodes = { a: node({ id: "a", name: "a", status: "running" }) };
    const todos = {
      a: [
        { taskId: "s1", content: "iter1 step", activeForm: "iter1 stepping", status: "completed", detail: null, iteration: 1 },
        { taskId: "s2", content: "iter2 step", activeForm: "iter2 stepping", status: "in_progress", detail: null, iteration: 2 },
      ],
    };
    const messages = [
      msg({ id: "1", nodeId: "a", agentName: "a", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "a", agentName: "a", timestamp: 200, iteration: 2 }),
    ];
    const items = deriveOutlineItems(nodes, messages, todos);
    const iter1 = items.find((i) => i.iteration === 1)!;
    const iter2 = items.find((i) => i.iteration === 2)!;
    // iter=2 is latest → running activity reads iter=2's step (s2)
    expect(iter2.activity).toMatchObject({ kind: "running", currentStepContent: "iter2 stepping" });
    // iter=1 is historical → completed (inferred), not the iter=2 step
    expect(iter1.activity.kind).toBe("completed");
  });

  it("isLatestIter is true only for the highest iteration of a node", () => {
    const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
      msg({ id: "3", nodeId: "coder", agentName: "coder", timestamp: 300, iteration: 3 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.isLatestIter).toBe(false);
    expect(items.find((i) => i.iteration === 2)?.isLatestIter).toBe(false);
    expect(items.find((i) => i.iteration === 3)?.isLatestIter).toBe(true);
  });

  it("token badge only appears on latest iter (Bug 1 visual fix)", () => {
    // Without isLatestIter gating, all three iter rows would show the
    // identical node-level tokenUsage under different "Iteration N/M" titles.
    const nodes = {
      coder: node({
        id: "coder",
        name: "coder",
        status: "success",
        tokenUsage: { input: 1000, output: 500, total: 1500 },
      }),
    };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.badges.find((b) => b.kind === "tokens")).toBeUndefined();
    expect(items.find((i) => i.iteration === 2)?.badges.find((b) => b.kind === "tokens")?.text).toBe("1.5k");
  });

  it("retry badge only appears on latest iter (decision 3 — display-only)", () => {
    const nodes = {
      coder: node({
        id: "coder",
        name: "coder",
        status: "retrying",
        retryAttempts: [
          { attempt: 1, maxAttempts: 3, category: "NetworkError", reason: "timeout", delayS: 2, retryAfterS: null, ts: 0 },
        ],
      }),
    };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.badges.find((b) => b.kind === "retry")).toBeUndefined();
    expect(items.find((i) => i.iteration === 2)?.badges.find((b) => b.kind === "retry")?.text).toBe("2/3");
  });

  it("historical iter status is inferred from messages (done → completed)", () => {
    // node.status is "running" because iter=2 is running, but iter=1
    // already completed — historical iter must infer from messages, not
    // use the live node.status (which would incorrectly show "running").
    const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "done" }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "streaming" }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.status).toBe("completed");
    expect(items.find((i) => i.iteration === 2)?.status).toBe("running");
  });

  it("historical iter with error message is marked failed", () => {
    const nodes = { coder: node({ id: "coder", name: "coder", status: "success" }) };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "error" }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "done" }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.status).toBe("failed");
    expect(items.find((i) => i.iteration === 2)?.status).toBe("completed");
  });

  it("latest iter picks up legacy TodoStep without iteration field (?? 1 fallback)", () => {
    // Single-iter scenario: legacy step has no iteration field. Default
    // `(t.iteration ?? 1) === 1` surfaces it under iter=1, which IS the
    // latest iter, so computeActivity reads it for the "running" subtitle.
    const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
    const todos = {
      coder: [
        { taskId: "legacy", content: "old", activeForm: "legacy stepping", status: "in_progress", detail: null },
      ],
    };
    const messages = [msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 })];
    const items = deriveOutlineItems(nodes, messages, todos);
    expect(items).toHaveLength(1);
    expect(items[0].iteration).toBe(1);
    expect(items[0].isLatestIter).toBe(true);
    expect(items[0].activity).toMatchObject({ kind: "running", currentStepContent: "legacy stepping" });
  });
});
