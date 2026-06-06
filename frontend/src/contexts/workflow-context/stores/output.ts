import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { OutputState } from "@/stores/outputStore";
import { createRafBatcher, type RafBatcher } from "@/lib/rafBatcher";

export function createOutputStore(
  workflowId: string,
): StoreApi<OutputState> {
  let outputBatcher: RafBatcher<string, string>;

  const initialState: OutputState = {
    texts: {},
    activeNodeId: null,
    workflowError: null,

    _cache: {},
    _activeWid: null,

    appendText: (nodeId, delta) => {
      /* Phase 2 实现 */
    },
    setActiveNode: (nodeId) => {
      /* Phase 2 实现 */
    },
    clearNode: (nodeId) => {
      /* Phase 2 实现 */
    },
    setWorkflowError: (error) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },

    saveToCache: (wid) => {
      /* Phase 2 实现 */
    },
    restoreFromCache: (wid) => false,
    setActiveWid: (wid) => {
      /* Phase 2 实现 */
    },
    clearCache: () => {
      /* Phase 2 实现 */
    },
  };

  const store = createStore<OutputState>()((set, get) => ({
    ...initialState,

    appendText: (nodeId, delta) => {
      outputBatcher.push(nodeId, delta, (prev, next) => prev + next);
    },

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

    reset: () => set({ texts: {}, activeNodeId: null, workflowError: null }),

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

  // Initialize batcher with store.setState now that store exists.
  outputBatcher = createRafBatcher<string, string>(
    (updates) => {
      store.setState((state) => {
        const texts = { ...state.texts };
        updates.forEach((d, nid) => {
          texts[nid] = (texts[nid] ?? "") + d;
        });
        return { texts };
      });
    },
  );

  return store;
}
