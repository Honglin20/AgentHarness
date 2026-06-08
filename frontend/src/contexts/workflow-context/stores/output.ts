import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { OutputState } from "@/stores/outputStore";
import { createRafBatcher, type RafBatcher } from "@/lib/rafBatcher";
import { withCache, type StoreCache, type WithCacheOptions } from "@/lib/storeCache";

export function createOutputStore(
  workflowId: string,
): StoreApi<OutputState> {
  let outputBatcher: RafBatcher<string, string>;

  // Only the data fields — method implementations live in createStore below
  // and override anything present here. Type is inferred from the literal so
  // we don't need no-op stubs for every action just to satisfy the type.
  const initialState = {
    texts: {} as Record<string, string>,
    activeNodeId: null as string | null,
    workflowError: null as string | null,

    _cache: {} as OutputState["_cache"],
    _activeWid: null as string | null,
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

    saveToCache: (wid) => cache.saveToCache(wid),
    restoreFromCache: (wid) => cache.restoreFromCache(wid),
    setActiveWid: (wid) => cache.setActiveWid(wid),
    clearCache: () => cache.clearCache(),
  }));

  // OutputState lacks a string index signature, but withCache only relies on
  // its internal _cache/_activeWid plumbing and casts internally — so widen the
  // store to satisfy the Record<string, unknown> constraint without touching
  // the typed OutputState interface. The options callbacks stay typed against
  // OutputState for snapshot correctness.
  const cacheOptions: WithCacheOptions<OutputState> = {
    extractSnapshot: (s) => ({ texts: s.texts, activeNodeId: s.activeNodeId }),
    applySnapshot: (_s, snap) => ({
      texts: (snap.texts as Record<string, string>) ?? {},
      activeNodeId: (snap.activeNodeId as string | null) ?? null,
    }),
    makeEmptySnapshot: () => ({ texts: {}, activeNodeId: null }),
  };
  const cache: StoreCache = withCache(
    store as unknown as StoreApi<Record<string, unknown>>,
    cacheOptions as unknown as WithCacheOptions<Record<string, unknown>>,
  );

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
