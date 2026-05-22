import { create } from "zustand";

export interface AgentIOData {
  inputPrompt: string;
  outputResult: unknown;
}

export interface AgentIOState {
  data: Record<string, AgentIOData>;
  setAgentIO: (nodeId: string, inputPrompt: string, outputResult: unknown) => void;
  reset: () => void;
}

const initialState = {
  data: {} as Record<string, AgentIOData>,
};

export const useAgentIOStore = create<AgentIOState>()((set) => ({
  ...initialState,

  setAgentIO: (nodeId, inputPrompt, outputResult) =>
    set((state) => ({
      data: {
        ...state.data,
        [nodeId]: { inputPrompt, outputResult },
      },
    })),

  reset: () => set(initialState),
}));