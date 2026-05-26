import { create } from "zustand";
import { setUserId, getUserId, getCurrentUser } from "@/lib/api";
import { useRunHistoryStore } from "./runHistoryStore";
import { useWorkflowStore } from "./workflowStore";
import { useOutputStore } from "./outputStore";
import { useChatStore } from "./chatStore";
import { useChartStore } from "./chartStore";
import { useToolCallStore } from "./toolCallStore";
import { useConversationStore } from "./conversationStore";
import { useViewStore } from "./viewStore";
import { useBatchStore } from "./batchStore";
import { useAgentIOStore } from "./agentIOStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

interface UserState {
  userId: string;
  name: string;
  role: string;
  loaded: boolean;

  /** Initialize user from localStorage on app start */
  initUser: () => Promise<void>;

  /** Switch to a different user — resets all stores and reloads data */
  switchUser: (userId: string, name: string, role: string) => void;
}

function resetAllStores() {
  setActiveWorkflowId(null);
  useWorkflowStore.getState().reset();
  useOutputStore.getState().reset();
  useChatStore.getState().reset();
  useChartStore.getState().reset();
  useToolCallStore.getState().reset();
  useConversationStore.getState().reset();
  useBatchStore.getState().setActiveBatch(null);
  useAgentIOStore.getState().reset();
  useRunHistoryStore.getState().reset();
  useViewStore.getState().showLive();
}

export const useUserStore = create<UserState>()((set) => ({
  userId: "",
  name: "",
  role: "",
  loaded: false,

  initUser: async () => {
    const storedId = getUserId();
    if (storedId) {
      const user = await getCurrentUser();
      if (user) {
        set({ userId: user.user_id, name: user.name, role: user.role, loaded: true });
        useRunHistoryStore.getState().fetchRuns();
        return;
      }
      // Stored user_id is invalid — clear it so user must re-select
      setUserId("");
    }
    // No valid user — mark loaded but don't set a fake user
    set({ userId: "", name: "", role: "", loaded: true });
  },

  switchUser: (userId, name, role) => {
    setUserId(userId);
    resetAllStores();
    set({ userId, name, role });
    useRunHistoryStore.getState().fetchRuns();
  },
}));
