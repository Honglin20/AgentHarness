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

describe("node.started handler — iteration caching from payload", () => {
  let stores: WorkflowStores;
  const startedHandler = nodeHandlers.find(([t]) => t === "node.started")![1];
  const completedHandler = nodeHandlers.find(([t]) => t === "node.completed")![1];

  beforeEach(() => {
    stores = makeStores();
  });

  it("reads iteration=1 from node.started payload (first invocation)", () => {
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }),
      {} as any,
    );
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });

  it("reads iteration=2 from subsequent node.started payload (loop)", () => {
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }),
      {} as any,
    );
    // Fire the actual node.completed event so the workflow store flips the
    // node status to non-running. Without this, node.started's idempotency
    // guard would skip the second fire.
    completedHandler(
      stores,
      fireEvent("node.completed", { node_id: "coder", agent_name: "coder", duration_ms: 100 }),
      {} as any,
    );
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 2 }),
      {} as any,
    );
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(2);
  });

  it("new agent message after second node.started is stamped with iteration=2", () => {
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }),
      {} as any,
    );
    // MUST fire the actual node.completed event (not handleNodeCompleted
    // directly) so completeAgentMessage flips the first agent message from
    // streaming→done. Otherwise addAgentMessage's streaming-guard no-ops
    // the second node.started and no iteration=2 message is ever created.
    completedHandler(
      stores,
      fireEvent("node.completed", { node_id: "coder", agent_name: "coder", duration_ms: 100 }),
      {} as any,
    );
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 2 }),
      {} as any,
    );
    const lastMsg = stores.conversation.getState().messages.at(-1);
    expect(lastMsg?.iteration).toBe(2);
  });

  it("falls back to iter=1 when payload lacks iteration (legacy event)", () => {
    // Pre-Plan-F events don't carry `iteration` — the handler must
    // degrade gracefully by treating absent as 1. This keeps old runs
    // replayable after the Plan F frontend deploy.
    startedHandler(
      stores,
      fireEvent("node.started", { node_id: "coder", agent_name: "coder" }),
      {} as any,
    );
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });
});
