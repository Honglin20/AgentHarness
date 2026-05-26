/**
 * useWorkflowEvents - Context 架构的事件处理 Hook
 *
 * 这是 Phase 2 的迁移版本
 * - 使用 eventRouter 分发事件到 scoped stores
 * - 支持单 workflow 和 batch 模式
 */

import { useCallback, useRef } from "react";
import type { WSEvent } from "@/types/events";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { UseWebSocketReturn } from "@/hooks/useWebSocket";
import { useBatchWebSocket } from "@/hooks/useBatchWebSocket";
import type { UseBatchWebSocketReturn } from "@/hooks/useBatchWebSocket";
import { dispatchSingleEvent } from "./eventRouter";
import { dispatchBatchEvent } from "./eventRouter";
import { getWorkflowManager } from "./WorkflowManager";
import { useBatchStore } from "@/stores/batchStore";
import { useWorkflowContext } from "./WorkflowContext";
import { useConversationActions, useChatActions } from "./hooks";

export interface ScopedWorkflowEventsReturn {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;
  send: (data: unknown) => void;
}

/**
 * useScopedWorkflowEvents
 *
 * Context 架构的 workflow events hook
 *
 * @param workflowId - 当前 workflow ID (null 表示 batch 模式)
 * @returns WebSocket 连接和交互方法
 */
export function useScopedWorkflowEvents(
  workflowId: string | null,
): ScopedWorkflowEventsReturn {
  const { workflowId: contextWorkflowId } = useWorkflowContext();
  const activeWorkflowId = workflowId ?? contextWorkflowId;
  const activeBatchId = useBatchStore((s) => s.activeBatchId);
  const batchMode = activeBatchId !== null;

  // Conversation and Chat actions
  const conversationActions = useConversationActions();
  const chatActions = useChatActions();

  // Track current mode to avoid hook dependency issues
  const currentModeRef = useRef(batchMode);
  currentModeRef.current = batchMode;

  const onEvent = useCallback((event: WSEvent) => {
    const isBatch = currentModeRef.current;
    if (isBatch) {
      dispatchBatchEvent(event);
    } else {
      dispatchSingleEvent(event, activeWorkflowId);
    }
  }, [activeWorkflowId]);

  // Always call both hooks (hooks rules)
  const singleWs = useWebSocket({
    workflowId: batchMode ? null : activeWorkflowId,
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
      chatActions.addUserAnswer(questionId, answer);
      conversationActions.addUserMessage(answer);
      conversationActions.clearPendingQuestion(questionId);
    },
    [ws.send, chatActions, conversationActions],
  );

  const sendStopAndRegenerate = useCallback(
    (agentName: string, partialOutput: string, userGuidance: string) => {
      if (!activeWorkflowId) return;
      ws.send({
        type: "agent.stop_and_regenerate",
        payload: {
          workflow_id: activeWorkflowId,
          agent_name: agentName,
          partial_output: partialOutput,
          user_guidance: userGuidance,
        },
      });
      conversationActions.interruptAgentMessage(agentName);
    },
    [ws.send, activeWorkflowId, conversationActions],
  );

  return { ...ws, sendAnswer, sendStopAndRegenerate };
}

/**
 * 设置活跃 workflow ID
 *
 * 用于在 workflows 之间切换
 */
export function setActiveWorkflowId(id: string | null): void {
  const manager = getWorkflowManager();
  manager.setActiveWorkflowId(id);
}