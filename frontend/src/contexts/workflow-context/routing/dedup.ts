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
 *
 * v3 (ADR: single-source-streaming-state D6): a third layer
 * _hydratedNodeTextCursorByWorkflow covers the text/thinking/tool_output
 * family per-node. Snapshot hydration now reverse-fills ConversationMessage
 * .thinking / .toolStreamingOutput from sidecars — those reducers
 * (appendAgentText / appendAgentThinking / appendToolOutput) are
 * append-unsafe, so without per-node cursor WS-replayed deltas would
 * double the content. The node-level cursor is the sidecar's last_seq.
 */

const _processedSeqsByWorkflow = new Map<string, Set<number>>();
const _hydratedCursorByWorkflow = new Map<string, number>();
// v3 D6: workflowId → (nodeId → last_seq). Per-node text/thinking/tool_output
// dedup cursor — set when loadRunFromPersistedData fills messages from sidecars.
const _hydratedNodeTextCursorByWorkflow = new Map<string, Map<string, number>>();
const SEQ_PRUNE_SIZE = 500;

export { _processedSeqsByWorkflow, SEQ_PRUNE_SIZE };

/** Remove the seq dedup tracker for a completed/destroyed workflow. */
export function cleanupSeqTracker(workflowId: string): void {
  _processedSeqsByWorkflow.delete(workflowId);
  _hydratedCursorByWorkflow.delete(workflowId);
  _hydratedNodeTextCursorByWorkflow.delete(workflowId);
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
 * v3 (ADR D6): set the per-node text/thinking/tool_output hydration cursor.
 *
 * Called by loadRunFromPersistedData when it reverse-fills ConversationMessage
 * .thinking / .toolStreamingOutput from sidecar data. Subsequent WS-replayed
 * text_delta / thinking_delta / tool_output_delta events with seq ≤ cursor
 * are skipped to prevent duplicate append (the content is already in the
 * hydrated message).
 *
 * Cursor source: sidecar.last_seq for that (workflow, node). When sidecar
 * lacks last_seq (legacy v2 sidecar), no cursor is set — fallback to the
 * workflow-level cursor (setHydratedCursor).
 */
export function setHydratedNodeTextCursor(
  workflowId: string,
  nodeId: string,
  cursor: number | null,
): void {
  let nodeMap = _hydratedNodeTextCursorByWorkflow.get(workflowId);
  if (!nodeMap) {
    nodeMap = new Map();
    _hydratedNodeTextCursorByWorkflow.set(workflowId, nodeMap);
  }
  if (cursor === null || typeof cursor !== "number" || !Number.isFinite(cursor) || cursor < 1) {
    nodeMap.delete(nodeId);
    if (nodeMap.size === 0) {
      _hydratedNodeTextCursorByWorkflow.delete(workflowId);
    }
    return;
  }
  // Monotonic — never lower an existing cursor (race protection).
  const prev = nodeMap.get(nodeId);
  if (prev !== undefined && cursor < prev) return;
  nodeMap.set(nodeId, cursor);
}

/**
 * v3 D6: query the per-node text/thinking/tool_output cursor.
 * Returns 0 when no cursor is set for this (workflow, node).
 */
export function getHydratedNodeTextCursor(
  workflowId: string,
  nodeId: string,
): number {
  return _hydratedNodeTextCursorByWorkflow.get(workflowId)?.get(nodeId) ?? 0;
}

/**
 * v3 D6: returns true if a text/thinking/tool_output_delta event with this
 * seq should be skipped because the hydrated sidecar already covered it.
 */
export function isTextNodeDuplicate(
  workflowId: string | undefined,
  nodeId: string | undefined,
  seq: number | undefined,
): boolean {
  if (typeof seq !== "number" || !workflowId || !nodeId) return false;
  const cursor = _hydratedNodeTextCursorByWorkflow.get(workflowId)?.get(nodeId);
  return cursor !== undefined && seq <= cursor;
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

