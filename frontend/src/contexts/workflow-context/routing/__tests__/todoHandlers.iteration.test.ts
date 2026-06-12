import { describe, it, expect, beforeEach } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";
import { createTodoStore } from "@/contexts/workflow-context/stores/todo";
import { createWorkflowStore } from "@/contexts/workflow-context/stores/workflow";
import { createOutputStore } from "@/contexts/workflow-context/stores/output";
import { todoHandlers } from "../todoHandlers";
import { nodeHandlers } from "../nodeHandlers";
import type { WorkflowStores } from "@/contexts/workflow-context/types";
import type { StoreApi } from "zustand/vanilla";
import type { ConversationState } from "@/stores/conversationStore";
import type { WorkflowState } from "@/stores/workflowStore";
import type { OutputState } from "@/stores/outputStore";
import type { TodoState } from "@/contexts/workflow-context/stores/todo";

function makeStores(): WorkflowStores {
  return {
    conversation: createConversationStore("wf-1") as StoreApi<ConversationState>,
    workflow: createWorkflowStore("wf-1") as StoreApi<WorkflowState>,
    output: createOutputStore("wf-1") as unknown as StoreApi<OutputState>,
    todo: createTodoStore("wf-1") as StoreApi<TodoState>,
  } as unknown as WorkflowStores;
}

function fireEvent(type: string, payload: Record<string, unknown>) {
  return { type, ts: Date.now(), payload, workflow_id: "wf-1" } as any;
}

describe("todo.created handler — iteration stamping from currentIterationByNode", () => {
  let stores: WorkflowStores;
  const startedHandler = nodeHandlers.find(([t]) => t === "node.started")![1];
  const completedHandler = nodeHandlers.find(([t]) => t === "node.completed")![1];
  const todoCreatedHandler = todoHandlers.find(([t]) => t === "todo.created")![1];

  beforeEach(() => {
    stores = makeStores();
  });

  it("first iter: node.started caches iter=1, todo.created stamps steps with iter=1", () => {
    // Plan F: iteration comes from the node.started payload (backend is
    // source of truth). The handler caches it into currentIterationByNode;
    // todo.created reads from that cache.
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }),
      {} as any,
    );
    todoCreatedHandler(
      stores,
      fireEvent("todo.created", {
        node_id: "coder",
        items: [{ task_id: "s1", content: "x", activeForm: "x", status: "in_progress", detail: null }],
      }),
      {} as any,
    );
    expect(stores.todo.getState().todos.coder[0].iteration).toBe(1);
  });

  it("loop: second iter stamps new steps with iter=2 (existing iter=1 steps untouched)", () => {
    // iter=1
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }),
      {} as any,
    );
    todoCreatedHandler(
      stores,
      fireEvent("todo.created", {
        node_id: "coder",
        items: [
          { task_id: "s1", content: "iter1a", activeForm: "iter1a", status: "in_progress", detail: null },
          { task_id: "s2", content: "iter1b", activeForm: "iter1b", status: "pending", detail: null },
        ],
      }),
      {} as any,
    );
    // iter=1 completes
    completedHandler(
      stores,
      fireEvent("node.completed", { node_id: "coder", agent_name: "coder", duration_ms: 100 }),
      {} as any,
    );
    // iter=2 — backend stamps iteration=2 in the node.started payload.
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 2 }),
      {} as any,
    );
    todoCreatedHandler(
      stores,
      fireEvent("todo.created", {
        node_id: "coder",
        items: [{ task_id: "s3", content: "iter2a", activeForm: "iter2a", status: "in_progress", detail: null }],
      }),
      {} as any,
    );

    const steps = stores.todo.getState().todos.coder;
    expect(steps).toHaveLength(3);
    expect(steps.find((s) => s.taskId === "s1")?.iteration).toBe(1);
    expect(steps.find((s) => s.taskId === "s2")?.iteration).toBe(1);
    expect(steps.find((s) => s.taskId === "s3")?.iteration).toBe(2);
  });

  it("todo.created before any node.started defaults to iter=1 (defensive)", () => {
    // Edge case: events arrive out of order (shouldn't happen in practice
    // — node.started is critical priority — but defensive default matters).
    todoCreatedHandler(
      stores,
      fireEvent("todo.created", {
        node_id: "coder",
        items: [{ task_id: "s1", content: "x", activeForm: "x", status: "in_progress", detail: null }],
      }),
      {} as any,
    );
    expect(stores.todo.getState().todos.coder[0].iteration).toBe(1);
  });
});
