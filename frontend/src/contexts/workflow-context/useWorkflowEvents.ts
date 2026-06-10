/**
 * useScopedWorkflowEvents — reads WS methods from WSMethodContext.
 *
 * No WebSocket creation — WS lives in WorkflowCenterPanel via useWorkflowWS.
 * This hook is safe to use inside WorkflowScope which may remount.
 */
import { useCallback } from "react";
import { useConversationActions } from "./hooks";
import { useWSMethods } from "./WorkflowScope";

export interface ScopedWorkflowEventsReturn {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
}

export function useScopedWorkflowEvents(): ScopedWorkflowEventsReturn {
  const ws = useWSMethods();
  const conversationActions = useConversationActions();

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.sendAnswer(questionId, answer);
      // Previously also wrote chatStore.addUserAnswer; chatStore was removed
      // in PR-F and conversationStore.addUserMessage below is the equivalent.
      conversationActions.addUserMessage(answer);
      conversationActions.clearPendingQuestion(questionId);
    },
    [ws, conversationActions],
  );

  const sendStructuredAnswer = useCallback(
    (questionId: string, answer: { selected: string[]; customInput: string }) => {
      ws.sendStructuredAnswer(questionId, answer);
      conversationActions.answerUserQuestion(questionId, answer);
    },
    [ws, conversationActions],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      ws.sendStopAndRegenerate(agentName, partialOutput, userGuidance);
      conversationActions.interruptAgentMessage(agentName);
    },
    [ws, conversationActions],
  );

  const sendGuidance = useCallback(
    (guidance: string) => {
      ws.sendGuidance(guidance);
    },
    [ws],
  );

  return { sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance };
}

export { setActiveWorkflowId } from "@/lib/workflowNavigation";
