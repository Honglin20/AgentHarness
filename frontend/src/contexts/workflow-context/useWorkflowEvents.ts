/**
 * useScopedWorkflowEvents — reads WS methods from WSMethodContext.
 *
 * No WebSocket creation — WS lives in WorkflowCenterPanel via useWorkflowWS.
 * This hook is safe to use inside WorkflowScope which may remount.
 */
import { useCallback } from "react";
import { useConversationActions, useChatActions } from "./hooks";
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
  const chatActions = useChatActions();

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      ws.sendAnswer(questionId, answer);
      chatActions.addUserAnswer(questionId, answer);
      conversationActions.addUserMessage(answer);
      conversationActions.clearPendingQuestion(questionId);
    },
    [ws, chatActions, conversationActions],
  );

  const sendStructuredAnswer = useCallback(
    (questionId: string, answer: { selected: string[]; customInput: string }) => {
      ws.sendStructuredAnswer(questionId, answer);
      chatActions.addUserAnswer(questionId, answer.customInput || answer.selected.join(", "));
      conversationActions.answerUserQuestion(questionId, answer);
    },
    [ws, chatActions, conversationActions],
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

export function setActiveWorkflowId(id: string | null): void {
  const { getWorkflowManager } = require("./WorkflowManager");
  getWorkflowManager().setActiveWorkflowId(id);
}
