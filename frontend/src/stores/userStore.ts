import { create } from "zustand";
import { setUserId, getUserId, getCurrentUser } from "@/lib/api";
import { useRunHistoryStore } from "./runHistoryStore";
import { resetAllGlobalStores } from "./resetGlobalStores";

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
    resetAllGlobalStores();
    set({ userId, name, role });
    useRunHistoryStore.getState().fetchRuns();
  },
}));
