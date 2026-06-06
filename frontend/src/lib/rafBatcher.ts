/**
 * RAF Batch Processor — coalesces high-frequency text deltas into a single
 * requestAnimationFrame flush. Each scoped store instance creates its own
 * batcher, so concurrent workflows never share state.
 */

export interface RafBatcher<TKey, TValue> {
  push(key: TKey, value: TValue, merge: (prev: TValue, next: TValue) => TValue): void;
  flush(): void;
  cancel(): void;
}

export function createRafBatcher<TKey, TValue>(
  apply: (updates: Map<TKey, TValue>) => void,
): RafBatcher<TKey, TValue> {
  let buf = new Map<TKey, TValue>();
  let seq = 0;
  let pending = false;

  function flush(): void {
    if (buf.size === 0) return;
    const updates = new Map(buf);
    buf.clear();
    seq++; // invalidate any pending RAF
    pending = false;
    apply(updates);
  }

  return {
    push(key, value, merge) {
      const existing = buf.get(key);
      buf.set(key, existing !== undefined ? merge(existing, value) : value);
      if (!pending) {
        pending = true;
        const capturedSeq = ++seq;
        requestAnimationFrame(() => {
          if (capturedSeq !== seq) return;
          flush();
        });
      }
    },

    flush,

    cancel() {
      seq++;
      pending = false;
    },
  };
}
