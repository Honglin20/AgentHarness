/**
 * Cast the backend outline sidecar DTO into the frontend `OutlineItem` shape.
 *
 * The sidecar is structurally isomorphic to `OutlineItem` (backend mirrors
 * `deriveOutlineItems.ts`); only the top-level keys differ in casing
 * (`node_id` → `nodeId`, `is_latest_iter` → `isLatestIter`). Nested
 * `activity` and `badges` are already camelCase because the backend emits
 * them in the same shape `computeActivity` / `computeBadges` produce.
 *
 * No information loss — the cast is a 1:1 projection. Adding a new field to
 * `OutlineItem` requires the backend to emit it (and a new mapping line here).
 */
import type { OutlineSummaryItem } from "@/stores/runHistoryStore";
import type { OutlineItem, AgentActivity, OutlineBadge } from "./types";

export function outlineSummaryToItems(summary: OutlineSummaryItem[]): OutlineItem[] {
  return summary.map((s) => ({
    key: s.key,
    nodeId: s.node_id,
    name: s.name,
    iteration: s.iteration,
    hasMultipleIterations: s.iter_count > 1,
    isLatestIter: s.is_latest_iter,
    status: s.status,
    activity: s.activity as AgentActivity,
    badges: s.badges as OutlineBadge[],
    order: s.order,
  }));
}
