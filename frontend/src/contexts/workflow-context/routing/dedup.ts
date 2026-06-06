/**
 * Universal dedup: skip events we've already processed (WS replay guard).
 */

const _processedSeqsByWorkflow = new Map<string, Set<number>>();
const SEQ_PRUNE_SIZE = 500;

export { _processedSeqsByWorkflow, SEQ_PRUNE_SIZE };

/** Remove the seq dedup tracker for a completed/destroyed workflow. */
export function cleanupSeqTracker(workflowId: string): void {
  _processedSeqsByWorkflow.delete(workflowId);
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
