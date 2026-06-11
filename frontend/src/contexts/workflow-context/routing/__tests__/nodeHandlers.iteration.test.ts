import { describe, it, expect, beforeEach } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";
import { createWorkflowStore } from "@/contexts/workflow-context/stores/workflow";
import { createOutputStore } from "@/contexts/workflow-context/stores/output";
import { nodeHandlers } from "../nodeHandlers";
import type { WorkflowStores } from "@/contexts/workflow-context/types";
import type { StoreApi } from "zustand/vanilla";
import type { ConversationState } from "@/stores/conversationStore";
import type { WorkflowState } from "@/stores/workflowStore";
import type { OutputState } from "@/stores/outputStore";

function makeStores(): WorkflowStores {
  return {
    conversation: createConversationStore("wf-1") as StoreApi<ConversationState>,
    workflow: createWorkflowStore("wf-1") as StoreApi<WorkflowState>,
    output: createOutputStore("wf-1") as unknown as StoreApi<OutputState>,
    // Other stores not needed for this test — cast through unknown.
  } as unknown as WorkflowStores;
}

function fireEvent(type: string, payload: Record<string, unknown>) {
  return { type, ts: Date.now(), payload, workflow_id: "wf-1" } as any;
}

describe("node.started handler — iteration counting", () => {
  let stores: WorkflowStores;
  const handler = nodeHandlers.find(([t]) => t === "node.started")![1];

  beforeEach(() => {
    stores = makeStores();
  });

  it("sets iteration=1 on first node.started for a nodeId", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });

  it("increments iteration on subsequent node.started for same nodeId (loop)", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    // Simulate the node completing — without this, the idempotency guard
    // in node.started would skip the second fire.
    stores.workflow.getState().handleNodeCompleted({ node_id: "coder", agent_name: "coder", duration_ms: 100 } as any);
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(2);
  });

  it("new agent message after second node.started is stamped with iteration=2", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    stores.workflow.getState().handleNodeCompleted({ node_id: "coder", agent_name: "coder", duration_ms: 100 } as any);
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    const lastMsg = stores.conversation.getState().messages.at(-1);
    expect(lastMsg?.iteration).toBe(2);
  });
});
