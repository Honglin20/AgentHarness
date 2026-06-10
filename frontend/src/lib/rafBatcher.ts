/**
 * RAF Batch Processor — coalesces high-frequency text deltas into a single
 * requestAnimationFrame flush. Each scoped store instance creates its own
 * batcher, so concurrent workflows never share state.
 *
 * Default behavior: flush on every RAF (~60Hz).
 * With `minIntervalMs`: throttle to a minimum interval between flushes.
 * Useful for high-frequency producers (text streaming) where 60Hz full-
 * array copies saturate the main thread.
 */

export interface RafBatcher<TKey, TValue> {
  push(key: TKey, value: TValue, merge: (prev: TValue, next: TValue) => TValue): void;
  flush(): void;
  cancel(): void;
}

export interface RafBatcherOptions {
  /**
   * Minimum interval between flushes, in ms. Default: undefined (flush on
   * every RAF, ~60Hz). Set to e.g. 33 to throttle to 30Hz, halving the
   * work for high-frequency producers like text streaming.
   */
  minIntervalMs?: number;
}

export function createRafBatcher<TKey, TValue>(
  apply: (updates: Map<TKey, TValue>) => void,
  options: RafBatcherOptions = {},
): RafBatcher<TKey, TValue> {
  const { minIntervalMs } = options;
  let buf = new Map<TKey, TValue>();
  let seq = 0;
  let pending = false;
  let lastFlushTs = 0;

  function flush(): void {
    if (buf.size === 0) return;
    const updates = new Map(buf);
    buf.clear();
    seq++;  // invalidate any pending RAF/timer
    pending = false;
    lastFlushTs = performance.now();
    apply(updates);
  }

  function schedule(): void {
    if (minIntervalMs === undefined) {
      const capturedSeq = ++seq;
      requestAnimationFrame(() => {
        if (capturedSeq !== seq) return;
        flush();
      });
      return;
    }
    // Throttled: wait at least minIntervalMs since last flush
    const elapsed = performance.now() - lastFlushTs;
    const wait = Math.max(0, minIntervalMs - elapsed);
    const capturedSeq = ++seq;
    setTimeout(() => {
      if (capturedSeq !== seq) return;
      flush();
    }, wait);
  }

  return {
    push(key, value, merge) {
      const existing = buf.get(key);
      buf.set(key, existing !== undefined ? merge(existing, value) : value);
      if (!pending) {
        pending = true;
        schedule();
      }
    },

    flush,

    cancel() {
      seq++;
      pending = false;
    },
  };
}
