import type { StoreApi } from "zustand/vanilla";

type CacheEntry = Record<string, unknown>;

export interface WithCacheOptions<TState> {
  /** Extract a serializable snapshot from the store's current state. */
  extractSnapshot: (state: TState) => CacheEntry;
  /** Apply a cached snapshot back to the store. Returns a partial state patch. */
  applySnapshot: (state: TState, snap: CacheEntry) => Partial<TState>;
  /** Build the snapshot used when setActiveWid lands on a wid with no cached entry. */
  makeEmptySnapshot: () => CacheEntry;
}

export interface StoreCache {
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
  /** Read a cached snapshot. Returns undefined if wid is unknown. */
  getCacheForWid: (wid: string) => CacheEntry | undefined;
  /** Ensure a snapshot exists for wid (inserting an empty/default if missing),
   *  or overwrite it with an explicit snap. Returns the (now-existing) snapshot. */
  setCacheForWid: (wid: string, snap?: CacheEntry) => CacheEntry;
}

export function withCache<TState extends Record<string, unknown>>(
  store: StoreApi<TState>,
  options: WithCacheOptions<TState>,
): StoreCache {
  return {
    saveToCache: (wid) => {
      const snap = options.extractSnapshot(store.getState());
      store.setState({
        _cache: { ...((store.getState() as Record<string, unknown>)["_cache"] as Record<string, CacheEntry> ?? {}), [wid]: snap },
      } as unknown as Partial<TState>);
    },

    restoreFromCache: (wid) => {
      const state = store.getState();
      const cache = (state as Record<string, unknown>)["_cache"] as Record<string, CacheEntry> | undefined;
      const snap = cache?.[wid];
      if (!snap) return false;
      store.setState(options.applySnapshot(state, snap));
      store.setState({ _activeWid: wid } as unknown as Partial<TState>);
      return true;
    },

    setActiveWid: (wid) => {
      const state = store.getState();
      const cache = { ...(((state as Record<string, unknown>)["_cache"] as Record<string, CacheEntry>) ?? {}) };
      const currentWid = (state as Record<string, unknown>)["_activeWid"] as string | null;

      if (currentWid && currentWid !== wid) {
        cache[currentWid] = options.extractSnapshot(state);
      }

      if (wid && cache[wid]) {
        const applied = options.applySnapshot(state, cache[wid]);
        store.setState({ ...applied, _cache: cache, _activeWid: wid } as unknown as Partial<TState>);
      } else {
        const applied = options.applySnapshot(state, options.makeEmptySnapshot());
        store.setState({ ...applied, _cache: cache, _activeWid: wid } as unknown as Partial<TState>);
      }
    },

    clearCache: () => {
      store.setState({ _cache: {}, _activeWid: null } as unknown as Partial<TState>);
    },

    getCacheForWid: (wid) => {
      const cache = (store.getState() as Record<string, unknown>)["_cache"] as Record<string, CacheEntry> | undefined;
      return cache?.[wid];
    },

    setCacheForWid: (wid, snap) => {
      const state = store.getState();
      const cache = { ...(((state as Record<string, unknown>)["_cache"] as Record<string, CacheEntry>) ?? {}) };
      if (!cache[wid]) {
        cache[wid] = snap ?? options.makeEmptySnapshot();
      } else if (snap) {
        cache[wid] = snap;
      }
      store.setState({ _cache: cache } as unknown as Partial<TState>);
      return cache[wid];
    },
  };
}
