import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";

export type ActiveView =
  | { type: "live" }
  | { type: "replay"; runId: string; run: RunRecord };

interface ViewState {
  activeView: ActiveView;
  showLive: () => void;
  showReplay: (run: RunRecord) => void;
}

export const useViewStore = create<ViewState>()((set) => ({
  activeView: { type: "live" },
  showLive: () => set({ activeView: { type: "live" } }),
  showReplay: (run) => set({ activeView: { type: "replay", runId: run.run_id, run } }),
}));
