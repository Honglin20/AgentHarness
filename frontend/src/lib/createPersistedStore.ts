import { createStore, type StoreApi, type StateCreator } from "zustand/vanilla";

const LOG = false;
function _log(...args: unknown[]) {
  if (LOG) console.log("[PersistedStore]", ...args);
}

export interface PersistenceConfig<T> {
  /** localStorage key prefix */
  key: string;
  /** Bump to invalidate stale data after schema changes */
  version: number;
  /** Only these fields are written to localStorage */
  partialize?: (state: T) => Partial<T>;
  /** Max serialized size in characters (default 512K). Oversized writes are skipped.
   *  Note: uses JSON.stringify().length which counts UTF-16 code units, not bytes.
   *  For ASCII-heavy payloads (JSON), this is approximately equal to byte size. */
  maxSize?: number;
  /** Debounce writes by this many ms (default 300) */
  debounceMs?: number;
}

interface StoredEnvelope {
  version: number;
  data: unknown;
}

/**
 * Create a Zustand vanilla store that automatically persists (a subset of)
 * its state to localStorage and rehydrates on creation.
 *
 * Design goals:
 *  - Zero runtime overhead on reads — persistence is a write-side concern
 *  - Size-gated — refuses to write payloads larger than `maxSize`
 *  - Versioned — bump `version` to discard stale schemas
 *  - Debounced — rapid setState calls are coalesced into one write
 *
 * Caveat: hydration uses shallow spread ({...base, ...hydrated}).
 * Only use this with flat or fully-persisted state shapes.
 * Designed for the "persisted vanilla store + transient zustand hook" pattern.
 */
export function createPersistedStore<T extends Record<string, unknown>>(
  config: PersistenceConfig<T>,
  stateCreator: StateCreator<T>,
): StoreApi<T> {
  const {
    key,
    version,
    partialize,
    maxSize = 512 * 1024,
    debounceMs = 300,
  } = config;

  const versionKey = `${key}__v`;
  const dataKey = `${key}__d`;

  // --- Hydrate -----------------------------------------------------------
  let hydrated: Partial<T> | undefined;
  try {
    const storedVersion = localStorage.getItem(versionKey);
    if (storedVersion === String(version)) {
      const raw = localStorage.getItem(dataKey);
      if (raw) {
        const parsed: StoredEnvelope = JSON.parse(raw);
        if (parsed.version === version && typeof parsed.data === "object" && parsed.data !== null) {
          hydrated = parsed.data as Partial<T>;
          _log(`hydrated ${key} from localStorage (${raw.length} bytes)`);
        }
      }
    } else {
      // Version mismatch — clear stale data
      localStorage.removeItem(versionKey);
      localStorage.removeItem(dataKey);
      _log(`cleared stale data for ${key} (stored=${storedVersion}, expected=${version})`);
    }
  } catch (err) {
    _log(`hydration failed for ${key}:`, err);
  }

  // --- Create store ------------------------------------------------------
  const store = createStore<T>()((...args) => {
    // Let stateCreator produce its defaults, then overlay hydrated data
    const base = stateCreator(...args);
    if (hydrated) {
      return { ...base, ...hydrated };
    }
    return base;
  });

  // --- Persist on change (debounced) ------------------------------------
  let writeTimer: ReturnType<typeof setTimeout> | null = null;

  function write() {
    writeTimer = null;
    try {
      const snapshot = store.getState();
      const toStore = partialize ? partialize(snapshot) : snapshot;
      const envelope: StoredEnvelope = { version, data: toStore };
      const serialized = JSON.stringify(envelope);

      if (serialized.length > maxSize) {
        _log(`skipping write for ${key}: ${serialized.length} bytes exceeds ${maxSize}`);
        return;
      }

      localStorage.setItem(versionKey, String(version));
      localStorage.setItem(dataKey, serialized);
      _log(`wrote ${key} (${serialized.length} bytes)`);
    } catch (err) {
      _log(`write failed for ${key}:`, err);
    }
  }

  // Debounced write: subscribe to store changes instead of monkey-patching setState.
  // This avoids TypeScript overload issues and works with all update paths.
  store.subscribe(() => {
    if (writeTimer) clearTimeout(writeTimer);
    writeTimer = setTimeout(write, debounceMs);
  });

  return store;
}
