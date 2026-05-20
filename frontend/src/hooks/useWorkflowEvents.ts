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
  ChatQuestionPayload,
  ChartRenderPayload,
} from "@/types/events";
import { useWebSocket } from "./useWebSocket";
import type { UseWebSocketReturn } from "./useWebSocket";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useChatStore } from "@/stores/chatStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChartStore } from "@/stores/chartStore";

// Cast through unknown — the switch on event.type guarantees the payload shape
function dispatchEvent(event: WSEvent): void {
  switch (event.type) {
    case "workflow.started":
      useWorkflowStore
        .getState()
        .handleWorkflowStarted(event.payload as unknown as WorkflowStartedPayload);
      break;

    case "workflow.completed":
      useWorkflowStore
        .getState()
        .handleWorkflowCompleted(event.payload as unknown as WorkflowCompletedPayload);
      break;

    case "node.started": {
      const p = event.payload as unknown as NodeStartedPayload;
      useWorkflowStore.getState().handleNodeStarted(p);
      useOutputStore.getState().setActiveNode(p.node_id);
      break;
    }

    case "node.completed": {
      const p = event.payload as unknown as NodeCompletedPayload;
      useWorkflowStore.getState().handleNodeCompleted(p);
      break;
    }

    case "node.failed": {
      const p = event.payload as unknown as NodeFailedPayload;
      useWorkflowStore.getState().handleNodeFailed(p);
      break;
    }

    case "agent.text_delta": {
      const p = event.payload as unknown as AgentTextDeltaPayload;
      useOutputStore.getState().appendText(p.node_id, p.text);
      break;
    }

    case "chat.question": {
      const p = event.payload as unknown as ChatQuestionPayload;
      useChatStore.getState().addAgentQuestion(p.question_id, p.question);
      break;
    }

    case "chart.render": {
      const p = event.payload as unknown as ChartRenderPayload;
      useChartStore.getState().addChart(p.chart);
      break;
    }

    case "workflow.error": {
      const p = event.payload as { workflow_id: string; error: string };
      useWorkflowStore.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      useOutputStore.getState().setWorkflowError(p.error);
      break;
    }
  }
}

export function useWorkflowEvents(
  workflowId: string | null,
): UseWebSocketReturn & { sendAnswer: (questionId: string, answer: string) => void } {
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
    },
    [ws.send],
  );

  return { ...ws, sendAnswer };
}
