/**
 * Universal dedup: skip events we've already processed (WS replay guard).
 *
 * Two layers:
 *   1. _processedSeqsByWorkflow — set of seqs already routed to reducers
 *      (used by replay to avoid double-dispatch)
 *   2. _hydratedCursorByWorkflow — watermark set by snapshot hydration.
 *      Any event with seq ≤ watermark is treated as duplicate (already
 *      reflected in snapshot state) and skipped, even if its seq isn't in
 *      the explicit set. This prevents WS-replayed events (delivered after
 *      snapshot hydrate via subscribe(since_seq=cursor)) from re-appending
 *      to idempotent-unsafe reducers (todo list / chart group / tool call order).
 */

const _processedSeqsByWorkflow = new Map<string, Set<number>>();
const _hydratedCursorByWorkflow = new Map<string, number>();
const SEQ_PRUNE_SIZE = 500;

export { _processedSeqsByWorkflow, SEQ_PRUNE_SIZE };

/** Remove the seq dedup tracker for a completed/destroyed workflow. */
export function cleanupSeqTracker(workflowId: string): void {
  _processedSeqsByWorkflow.delete(workflowId);
  _hydratedCursorByWorkflow.delete(workflowId);
}

/**
 * Set the snapshot hydration watermark for a workflow. Called after the
 * frontend hydrates all scoped stores from GET /api/runs/{id}/snapshot.
 * Any subsequent event with seq ≤ cursor is treated as a duplicate
 * (snapshot already reflects that state) and skipped by isDuplicate().
 *
 * Passing null clears the watermark (used on store reset / workflow switch).
 */
export function setHydratedCursor(
  workflowId: string,
  cursor: number | null,
): void {
  if (cursor === null) {
    _hydratedCursorByWorkflow.delete(workflowId);
    return;
  }
  if (typeof cursor !== "number" || !Number.isFinite(cursor) || cursor < 0) {
    return;
  }
  _hydratedCursorByWorkflow.set(workflowId, cursor);
}

/**
 * Check if an event is a duplicate (already processed seq for this workflow).
 * Returns true if the event should be skipped.
 * Also handles pruning of the seq set when it grows too large.
 */
export function isDuplicate(
  workflowId: string | undefined,
  seq: number | undefined
): boolean {
  if (typeof seq !== "number" || !workflowId) return false;

  // Hydration watermark: snapshot already reflected everything ≤ cursor.
  const cursor = _hydratedCursorByWorkflow.get(workflowId);
  if (cursor !== undefined && seq <= cursor) return true;

  let seqs = _processedSeqsByWorkflow.get(workflowId);
  if (!seqs) {
    seqs = new Set<number>();
    _processedSeqsByWorkflow.set(workflowId, seqs);
  }
  if (seqs.has(seq)) return true;
  seqs.add(seq);
  if (seqs.size > SEQ_PRUNE_SIZE) {
    const entries = Array.from(seqs).sort((a, b) => a - b);
    const toKeep = entries.slice(-SEQ_PRUNE_SIZE / 2);
    seqs.clear();
    toKeep.forEach((s) => seqs.add(s));
  }
  return false;
}
