"use client";

import { useCallback } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { useToolCallStore } from "@/stores/toolCallStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useViewStore } from "@/stores/viewStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

/** Reset all live workflow state and return to the landing page. */
export function useResetWorkflow() {
  return useCallback(() => {
    useWorkflowStore.getState().reset();
    useOutputStore.getState().reset();
    useChatStore.getState().reset();
    useChartStore.getState().reset();
    useToolCallStore.getState().reset();
    useConversationStore.getState().reset();
    useViewStore.getState().showLive();
    setActiveWorkflowId(null);
  }, []);
}
