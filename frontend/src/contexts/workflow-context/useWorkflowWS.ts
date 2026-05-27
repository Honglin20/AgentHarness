/**
 * useWorkflowWS — WebSocket lifecycle for Context architecture.
 *
 * Lives in WorkflowCenterPanel (stable parent). Reconnects naturally
 * when workflowId changes. Routes events via eventRouter to scoped stores.
 */
import { useCallback } from "react";
import type { WSEvent } from "@/types/events";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useBatchWebSocket } from "@/hooks/useBatchWebSocket";
import { dispatchSingleEvent } from "./eventRouter";
import { dispatchBatchEvent } from "./eventRouter";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowStore } from "@/stores/workflowStore";

export interface WorkflowWSReturn {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

export function useWorkflowWS(workflowId: string | null): WorkflowWSReturn {
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchMode = activeBatchId !== null;

  const onEvent = useCallback((event: WSEvent) => {
    if (batchMode) {
      dispatchBatchEvent(event);
    } else {
      const activeWid = useWorkflowStore.getState().activeWorkflowId;
      dispatchSingleEvent(event, activeWid);
    }
  }, [batchMode]);

  const singleWs = useWebSocket({
    workflowId: batchMode ? null : workflowId,
    onEvent,
  });

  const batchWs = useBatchWebSocket({
    batchId: activeBatchId ?? "",
    onEvent,
  });

  const ws = batchMode ? batchWs : singleWs;

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.send({ type: "chat.answer", payload: { question_id: questionId, answer } });
    },
    [ws],
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
    [ws, workflowId],
  );

  return { sendAnswer, sendStopAndRegenerate };
}
