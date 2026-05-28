import { create } from "zustand";

export interface CircularWarning {
  nodeId: string;
  agentName: string;
  message: string;
  lastTool: string | null;
  ts: number;
}

export interface ObservabilityState {
  circularWarnings: CircularWarning[];
  addCircularWarning: (warning: CircularWarning) => void;
  clear: () => void;
}

export const useObservabilityStore = create<ObservabilityState>((set) => ({
  circularWarnings: [],
  addCircularWarning: (w) =>
    set((state) => ({
      circularWarnings: [...state.circularWarnings, w],
    })),
  clear: () => set({ circularWarnings: [] }),
}));
