import { useEffect, useRef, useState } from "react";

/**
 * Pure decision function — extracted so it can be unit-tested without
 * needing @testing-library/react's renderHook. Returns true if the count
 * should reset to `initial`, based on whether `resetKey` changed since
 * the previous render.
 *
 * Bug being fixed: ScopedConversationTab previously did
 *   useEffect(() => setVisibleCount(VISIBLE_WINDOW), [messages])
 * which fired 60×/sec during streaming (messages ref changes every text
 * batch) AND wiped out user-loaded earlier messages.
 *
 * The fix ties reset to workflowId — streaming chunks grow messages but
 * don't change workflowId; switching runs does.
 */
export function shouldResetVisibleCount(
  prevKey: unknown,
  nextKey: unknown,
): boolean {
  return prevKey !== nextKey;
}

/**
 * Like useState for a count, but auto-resets to `initial` when `resetKey`
 * changes. Used by ScopedConversationTab to reset the visible-window on
 * run switch (workflowId change), NOT on every streaming chunk.
 */
export function useStableVisibleCount(
  initial: number,
  resetKey: unknown,
): [number, (updater: (c: number) => number) => void] {
  const prevKeyRef = useRef(resetKey);
  const [count, setCount] = useState(initial);
  useEffect(() => {
    if (shouldResetVisibleCount(prevKeyRef.current, resetKey)) {
      setCount(initial);
      prevKeyRef.current = resetKey;
    }
  }, [resetKey, initial]);
  return [count, setCount];
}
