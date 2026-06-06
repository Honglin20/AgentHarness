import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { AgentIOState } from "@/stores/agentIOStore";

export function createAgentIOStore(
  workflowId: string,
): StoreApi<AgentIOState> {
  const initialState: AgentIOState = {
    data: {},

    setAgentIO: (nodeId, inputPrompt, outputResult, systemPrompt) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<AgentIOState>()((set) => ({
    ...initialState,

    setAgentIO: (nodeId, inputPrompt, outputResult, systemPrompt) =>
      set((state) => ({
        data: {
          ...state.data,
          [nodeId]: {
            inputPrompt,
            outputResult,
            systemPrompt,
          },
        },
      })),

    reset: () => set({ data: {} }),
  }));
}
