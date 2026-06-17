import { create } from "zustand";

export type OutlineViewMode = "outline" | "timeline";

/**
 * Selection + view-mode state for the conversation panel.
 *
 * Kept in its own store (not in conversationStore) so that:
 *   - Resetting conversation data on run switch doesn't blow away the
 *     user's view preference (outline vs timeline).
 *   - Detail view consumers don't re-render when unrelated conversation
 *     mutations happen.
 *
 * Selection model (Phase 3 of outline-iter-collapse, 2026-06-17):
 *   - `selectedNodeId` — which agent is shown in the detail panel. The
 *     sidebar now folds iters into one row per agent, so selection is by
 *     nodeId, not by `${nodeId}__iter${n}` key.
 *   - `selectedIterByNode` — per-agent iter choice made via the detail
 *     panel's iter dropdown. Absent entry means "use latestIter". Preserved
 *     across agent switches so flipping back to an agent restores the user's
 *     last-viewed iter (Decision 2 in the plan).
 *
 * Lifecycle:
 *   - autoFollow defaults on; selecting an item manually turns it off
 *     (so the user's choice "sticks" when a new agent starts running).
 *     The user can re-enable autoFollow via a button.
 */
interface OutlineState {
  selectedNodeId: string | null;
  /** Per-nodeId iter choice; absence = latestIter fallback. */
  selectedIterByNode: Record<string, number>;
  autoFollow: boolean;
  viewMode: OutlineViewMode;

  /** Select an agent (by nodeId). keepAutoFollow=true preserves autoFollow
   *  (rare — used when autoFollow itself triggers the selection).
   *  Does NOT touch selectedIterByNode — user's per-agent iter choice persists. */
  select: (nodeId: string | null, keepAutoFollow?: boolean) => void;
  /** Switch the iter shown for a given agent in the detail panel. */
  selectIter: (nodeId: string, iter: number) => void;
  setAutoFollow: (on: boolean) => void;
  setViewMode: (mode: OutlineViewMode) => void;
  /** Low-level setter for tests + advanced callers. */
  setState: (partial: Partial<Pick<OutlineState, "selectedNodeId" | "selectedIterByNode" | "autoFollow" | "viewMode">>) => void;
  /** Reset to defaults but preserve viewMode (user preference). */
  reset: () => void;
}

export const useOutlineStore = create<OutlineState>()((set) => ({
  selectedNodeId: null,
  selectedIterByNode: {},
  autoFollow: true,
  viewMode: "outline",

  select: (nodeId, keepAutoFollow = false) =>
    set((s) => ({
      selectedNodeId: nodeId,
      autoFollow: keepAutoFollow ? s.autoFollow : false,
    })),

  selectIter: (nodeId, iter) =>
    set((s) => ({
      selectedIterByNode: { ...s.selectedIterByNode, [nodeId]: iter },
    })),

  setAutoFollow: (on) => set({ autoFollow: on }),

  setViewMode: (mode) => set({ viewMode: mode }),

  setState: (partial) => set(partial),

  reset: () =>
    set((s) => ({
      selectedNodeId: null,
      selectedIterByNode: {},
      autoFollow: true,
      viewMode: s.viewMode,
    })),
}));
