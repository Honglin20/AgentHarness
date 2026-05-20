import { create } from "zustand";

export interface OutputState {
  // Streamed text per node, keyed by node_id
  texts: Record<string, string>;

  // Current active node (the one being streamed)
  activeNodeId: string | null;

  // Workflow-level error message
  workflowError: string | null;

  // Actions
  appendText: (nodeId: string, delta: string) => void;
  setActiveNode: (nodeId: string | null) => void;
  clearNode: (nodeId: string) => void;
  setWorkflowError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  texts: {} as Record<string, string>,
  activeNodeId: null as string | null,
  workflowError: null as string | null,
};

export const useOutputStore = create<OutputState>()((set) => ({
  ...initialState,

  appendText: (nodeId, delta) =>
    set((state) => ({
      texts: {
        ...state.texts,
        [nodeId]: (state.texts[nodeId] ?? "") + delta,
      },
    })),

  setActiveNode: (nodeId) => set({ activeNodeId: nodeId }),

  clearNode: (nodeId) =>
    set((state) => {
      const { [nodeId]: _, ...rest } = state.texts;
      return {
        texts: rest,
        activeNodeId: state.activeNodeId === nodeId ? null : state.activeNodeId,
      };
    }),

  setWorkflowError: (error) => set({ workflowError: error }),

  reset: () => set(initialState),
}));
