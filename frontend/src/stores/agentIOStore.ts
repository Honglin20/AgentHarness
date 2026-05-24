import { create } from "zustand";

export interface AgentIOData {
  inputPrompt: string;
  systemPrompt?: string;
  outputResult: unknown;
}

export interface AgentIOState {
  data: Record<string, AgentIOData>;
  setAgentIO: (nodeId: string, inputPrompt: string, outputResult: unknown, systemPrompt?: string) => void;
  reset: () => void;
}

const initialState = {
  data: {} as Record<string, AgentIOData>,
};

export const useAgentIOStore = create<AgentIOState>()((set) => ({
  ...initialState,

  setAgentIO: (nodeId, inputPrompt, outputResult, systemPrompt) =>
    set((state) => ({
      data: {
        ...state.data,
        [nodeId]: { inputPrompt, outputResult, systemPrompt },
      },
    })),

  reset: () => set(initialState),
}));