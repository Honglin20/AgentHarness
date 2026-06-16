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
import { useAppViewStore } from "@/stores/appView";

export interface WorkflowWSReturn {
  isConnected: boolean;
  sendAnswer: (questionId: string, answer: string) => void;
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
  sendFollowup: (agentName: string, question: string) => void;
}

export function useWorkflowWS(workflowId: string | null): WorkflowWSReturn {
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchMode = activeBatchId !== null;
  // WS since_seq cursor — when >0, the WS only fetches events after the
  // snapshot cursor (set by activateRun after snapshot hydrate). When 0
  // (default / fallback), the WS replays the entire bus buffer.
  const wsSinceSeq = useAppViewStore((s) => s.wsSinceSeq);

  const onEvent = useCallback((event: WSEvent) => {
    if (batchMode) {
      dispatchBatchEvent(event);
    } else {
      dispatchSingleEvent(event, workflowId);
    }
  }, [batchMode, workflowId]);

  const singleWs = useWebSocket({
    workflowId: batchMode ? null : workflowId,
    onEvent,
    sinceSeq: wsSinceSeq,
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

  const sendStructuredAnswer = useCallback(
    (questionId: string, answer: { selected: string[]; customInput: string }) => {
      ws.send({
        type: "chat.answer",
        payload: {
          question_id: questionId,
          selected: answer.selected,
          custom_input: answer.customInput,
        },
      });
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

  const sendGuidance = useCallback(
    (guidance: string) => {
      if (!workflowId) return;
      ws.send({
        type: "agent.provide_guidance",
        payload: {
          workflow_id: workflowId,
          guidance,
        },
      });
    },
    [ws, workflowId],
  );

  const sendFollowup = useCallback(
    (agentName: string, question: string) => {
      if (!workflowId) return;
      ws.send({
        type: "chat.followup",
        payload: {
          agent_name: agentName,
          question,
        },
      });
    },
    [ws, workflowId],
  );

  return { isConnected: ws.isConnected, sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup };
}
