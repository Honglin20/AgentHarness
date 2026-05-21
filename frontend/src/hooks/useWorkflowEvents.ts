"use client";

import { useCallback } from "react";
import type {
  WSEvent,
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  ChatQuestionPayload,
  ChartRenderPayload,
} from "@/types/events";
import { useWebSocket } from "./useWebSocket";
import type { UseWebSocketReturn } from "./useWebSocket";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChartStore } from "@/stores/chartStore";
import { useToolCallStore, nextToolCallId } from "@/stores/toolCallStore";
import { useConversationStore } from "@/stores/conversationStore";

// Track the current workflow to filter stale replayed events
let _activeWorkflowId: string | null = null;

/** Save conversation messages to the backend for a completed/failed run. */
function _saveConversation(workflowId: string | undefined): void {
  if (!workflowId) return;
  const messages = useConversationStore.getState().messages;
  fetch(`/api/runs/${workflowId}/conversation`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation: messages }),
  }).catch(() => {
    // Best-effort — don't block UI on failure
  });
}

/** Save chartStore snapshot (groups + groupOrder) so the Results tab replays. */
function _saveCharts(workflowId: string | undefined): void {
  if (!workflowId) return;
  const { groups, groupOrder } = useChartStore.getState();
  if (groupOrder.length === 0) return;  // nothing to save
  fetch(`/api/runs/${workflowId}/charts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chart_groups: { groups, groupOrder } }),
  }).catch(() => {});
}

// Cast through unknown — the switch on event.type guarantees the payload shape
function dispatchEvent(event: WSEvent): void {
  const payloadWid = event.payload?.workflow_id as string | undefined;

  // Filter out stale events from previous workflows.
  // Once we see a workflow.started, lock to that workflow_id.
  switch (event.type) {
    case "workflow.started": {
      const p = event.payload as unknown as WorkflowStartedPayload;
      // If we already locked to a workflow_id (set via setActiveWorkflowId
      // before connecting), ignore any replayed/stale workflow.started events
      // for a different workflow.
      if (_activeWorkflowId && p.workflow_id !== _activeWorkflowId) break;
      _activeWorkflowId = p.workflow_id;
      useWorkflowStore.getState().handleWorkflowStarted(p);
      useConversationStore.getState().addSystemMessage("Workflow started: " + p.name);
      break;
    }

    case "workflow.completed": {
      const p = event.payload as unknown as WorkflowCompletedPayload;
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      useWorkflowStore
        .getState()
        .handleWorkflowCompleted(p);
      // Persist conversation + charts to backend
      _saveConversation(payloadWid);
      _saveCharts(payloadWid);
      break;
    }

    case "node.started": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as NodeStartedPayload;
      useWorkflowStore.getState().handleNodeStarted(p);
      useOutputStore.getState().setActiveNode(p.node_id);
      useConversationStore.getState().addAgentMessage(p.node_id, p.agent_name);
      break;
    }

    case "node.completed": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as NodeCompletedPayload;
      useWorkflowStore.getState().handleNodeCompleted(p);
      useConversationStore.getState().completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);
      break;
    }

    case "node.failed": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as NodeFailedPayload;
      useWorkflowStore.getState().handleNodeFailed(p);
      useConversationStore.getState().failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
      break;
    }

    case "agent.text_delta": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as AgentTextDeltaPayload;
      useOutputStore.getState().appendText(p.node_id, p.text);
      useConversationStore.getState().appendAgentText(p.node_id, p.text);
      break;
    }

    case "agent.tool_call": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as AgentToolCallPayload;
      const id = nextToolCallId();
      useToolCallStore.getState().addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      useConversationStore.getState().addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      break;
    }

    case "agent.tool_result": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as AgentToolResultPayload;
      // Find the most recent tool call for this node+tool without a result
      const store = useToolCallStore.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find((r) => r.nodeId === p.node_id && r.toolName === p.tool_name && r.result === undefined);
      if (match) {
        useToolCallStore.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      useConversationStore.getState().addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
      break;
    }

    case "chat.question": {
      const p = event.payload as unknown as ChatQuestionPayload;
      useChatStore.getState().addAgentQuestion(p.question_id, p.question);
      // Derive agent name from the most recent streaming agent message, or default to "agent"
      const conv = useConversationStore.getState();
      const lastStreaming = [...conv.messages].reverse().find((m) => m.type === "agent" && m.status === "streaming");
      const agentName = lastStreaming?.agentName ?? "agent";
      conv.addAgentQuestion(p.question_id, p.question, agentName);
      break;
    }

    case "chart.render": {
      const p = event.payload as unknown as ChartRenderPayload;
      useChartStore.getState().addChart(p.chart);
      break;
    }

    case "workflow.error": {
      const p = event.payload as { workflow_id: string; error: string };
      if (p.workflow_id && p.workflow_id !== _activeWorkflowId) break;
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      useOutputStore.getState().setWorkflowError(p.error);
      // Persist conversation + charts to backend
      _saveConversation(p.workflow_id);
      _saveCharts(p.workflow_id);
      break;
    }

    case "workflow.resumed": {
      // Agent resumed after interrupt — no special UI action needed,
      // text_delta events will continue flowing
      useConversationStore.getState().addSystemMessage("Workflow resumed");
      break;
    }
  }
}

/** Set the active workflow ID before the WebSocket connects so that
 *  replayed events are filtered correctly from the start. */
export function setActiveWorkflowId(id: string | null) {
  _activeWorkflowId = id;
}

export function useWorkflowEvents(
  workflowId: string | null,
): UseWebSocketReturn & {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
} {
  const onEvent = useCallback((event: WSEvent) => {
    dispatchEvent(event);
  }, []);

  const ws = useWebSocket({
    workflowId,
    onEvent,
  });

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.send({ type: "chat.answer", payload: { question_id: questionId, answer } });
      useChatStore.getState().addUserAnswer(questionId, answer);
      useConversationStore.getState().addUserMessage(answer);
      useConversationStore.getState().clearPendingQuestion(questionId);
    },
    [ws.send],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      if (!workflowId) return;
      ws.send({
        type: "agent.stop_and_regenerate",
        payload: {
          workflow_id: workflowId,
          agent_name: agentName,
          partial_output: partialOutput,
          user_guidance: userGuidance,
        },
      });
    },
    [ws.send, workflowId],
  );

  return { ...ws, sendAnswer, sendStopAndRegenerate };
}
