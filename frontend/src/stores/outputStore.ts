import { create } from "zustand";

export interface OutputState {
  // Streamed text per node, keyed by node_id
  texts: Record<string, string>;

  // Current active node (the one being streamed)
  activeNodeId: string | null;

  // Workflow-level error message
  workflowError: string | null;

  // Per-workflow cache for batch mode
  _cache: Record<string, { texts: Record<string, string>; activeNodeId: string | null }>;
  _activeWid: string | null;

  // Actions
  appendText: (nodeId: string, delta: string) => void;
  setActiveNode: (nodeId: string | null) => void;
  clearNode: (nodeId: string) => void;
  setWorkflowError: (error: string | null) => void;
  reset: () => void;

  // Cache management for batch mode
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
}

const initialState = {
  texts: {} as Record<string, string>,
  activeNodeId: null as string | null,
  workflowError: null as string | null,
  _cache: {} as Record<string, { texts: Record<string, string>; activeNodeId: string | null }>,
  _activeWid: null as string | null,
};

export const useOutputStore = create<OutputState>()((set, get) => ({
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

  reset: () => set({ ...initialState, _cache: get()._cache }),

  saveToCache: (wid) => {
    const { texts, activeNodeId, _cache } = get();
    _cache[wid] = { texts, activeNodeId };
    set({ _cache });
  },

  restoreFromCache: (wid) => {
    const snap = get()._cache[wid];
    if (!snap) return false;
    set({ texts: snap.texts, activeNodeId: snap.activeNodeId, _activeWid: wid });
    return true;
  },

  setActiveWid: (wid) => {
    const { _activeWid, _cache } = get();
    if (_activeWid) {
      _cache[_activeWid] = { texts: get().texts, activeNodeId: get().activeNodeId };
    }
    if (wid && _cache[wid]) {
      const snap = _cache[wid];
      set({ texts: snap.texts, activeNodeId: snap.activeNodeId, _activeWid: wid, _cache });
    } else {
      set({ texts: {}, activeNodeId: null, _activeWid: wid, _cache });
    }
  },

  clearCache: () => set({ _cache: {}, _activeWid: null }),
}));
