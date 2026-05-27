/**
 * useScopedWorkflowEvents — reads WS methods from WSMethodProvider.
 *
 * No longer creates WebSocket connections — those live in WorkflowCenterPanel
 * via useWorkflowWS. This hook is safe to use inside WorkflowScope which may
 * remount on workflow switches, since it has no WS lifecycle of its own.
 */
import { useCallback } from "react";
import { useConversationActions, useChatActions } from "./hooks";
import { useWorkflowContext } from "./WorkflowContext";
import { getWSMethods } from "./WorkflowScope";

export interface ScopedWorkflowEventsReturn {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

export function useScopedWorkflowEvents(): ScopedWorkflowEventsReturn {
  const { workflowId: activeWorkflowId } = useWorkflowContext();
  const conversationActions = useConversationActions();
  const chatActions = useChatActions();

  const sendAnswer = useCallback(
    (questionId: string, answer: string) => {
      const ws = getWSMethods();
      ws.sendAnswer?.(questionId, answer);
      chatActions.addUserAnswer(questionId, answer);
      conversationActions.addUserMessage(answer);
      conversationActions.clearPendingQuestion(questionId);
    },
    [chatActions, conversationActions],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      const ws = getWSMethods();
      ws.sendStopAndRegenerate?.(agentName, partialOutput, userGuidance);
      conversationActions.interruptAgentMessage(agentName);
    },
    [conversationActions],
  );

  return { sendAnswer, sendStopAndRegenerate };
}

export function setActiveWorkflowId(id: string | null): void {
  const { getWorkflowManager } = require("./WorkflowManager");
  getWorkflowManager().setActiveWorkflowId(id);
}
