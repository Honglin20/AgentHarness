/**
 * Fold `OutlineItem[]` (one entry per (nodeId, iter)) into `OutlineGroup[]`
 * (one entry per nodeId) at the view layer.
 *
 * Why view-layer folding (vs. changing sidecar schema / deriveOutlineItems):
 *   - Sidecar writes one row per iter on each node completion — incremental
 *     and append-only. Bundling iters into a single record per nodeId would
 *     either require rewriting the whole record on every iter or storing
 *     redundant per-iter metadata.
 *   - `deriveOutlineItems` already emits per-iter; grouping downstream keeps
 *     the single source of truth unchanged.
 *   - Grouping is O(N) memoized — N is bounded by agents × iters (200×4 = 800
 *     at the extreme), well under a millisecond.
 *
 * Semantics:
 *   - Input order doesn't matter; output is sorted by first-appearance (min
 *     `order` across the group's iters), so the sidebar still mirrors the
 *     DAG declaration / first-message timeline.
 *   - `iters` within a group are sorted ascending by `iteration`.
 *   - `latest` is the highest-iteration item; its status / activity / badges
 *     drive the sidebar row.
 *   - `name` comes from the latest iter so renames mid-run surface.
 */
import type { OutlineItem, OutlineGroup } from "./types";

export function groupOutlineByNode(items: OutlineItem[]): OutlineGroup[] {
  if (items.length === 0) return [];

  // Group by nodeId, preserving first-appearance order via Map insertion semantics.
  const groups = new Map<string, OutlineItem[]>();
  for (const item of items) {
    const arr = groups.get(item.nodeId);
    if (arr) arr.push(item);
    else groups.set(item.nodeId, [item]);
  }

  const result: OutlineGroup[] = [];
  // Array.from avoids Map iterator downlevelIteration errors when tsconfig
  // has no explicit `target` (Next.js infers one, but tsc --noEmit still
  // complains). forEach would also work but for...of reads more naturally.
  for (const iters of Array.from(groups.values())) {
    // Sort by iteration ascending so `iters[N-1]` corresponds to iter N.
    // Input may be unsorted if events arrived out of order during replay.
    iters.sort((a: OutlineItem, b: OutlineItem) => a.iteration - b.iteration);
    const latest = iters[iters.length - 1];
    const minOrder = iters.reduce(
      (min: number, it: OutlineItem) => (it.order < min ? it.order : min),
      iters[0].order,
    );

    result.push({
      nodeId: latest.nodeId,
      name: latest.name,
      latest,
      iterCount: iters.length,
      latestIteration: latest.iteration,
      iters,
      order: minOrder,
    });
  }

  // Sort groups by min order so first-appearance position is preserved.
  result.sort((a, b) => a.order - b.order);
  return result;
}
