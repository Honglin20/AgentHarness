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
 * Lifecycle:
 *   - selectedKey follows the `${nodeId}__iter${n}` shape from OutlineItem.
 *   - autoFollow defaults on; selecting an item manually turns it off
 *     (so the user's choice "sticks" when a new agent starts running).
 *     The user can re-enable autoFollow via a button.
 */
interface OutlineState {
  selectedKey: string | null;
  autoFollow: boolean;
  viewMode: OutlineViewMode;

  /** Select an outline entry. keepAutoFollow=true preserves autoFollow
   *  (rare — used when autoFollow itself triggers the selection). */
  select: (key: string | null, keepAutoFollow?: boolean) => void;
  setAutoFollow: (on: boolean) => void;
  setViewMode: (mode: OutlineViewMode) => void;
  /** Low-level setter for tests + advanced callers. */
  setState: (partial: Partial<Pick<OutlineState, "selectedKey" | "autoFollow" | "viewMode">>) => void;
  /** Reset to defaults but preserve viewMode (user preference). */
  reset: () => void;
}

export const useOutlineStore = create<OutlineState>()((set) => ({
  selectedKey: null,
  autoFollow: true,
  viewMode: "outline",

  select: (key, keepAutoFollow = false) =>
    set((s) => ({
      selectedKey: key,
      autoFollow: keepAutoFollow ? s.autoFollow : false,
    })),

  setAutoFollow: (on) => set({ autoFollow: on }),

  setViewMode: (mode) => set({ viewMode: mode }),

  setState: (partial) => set(partial),

  reset: () =>
    set((s) => ({
      selectedKey: null,
      autoFollow: true,
      viewMode: s.viewMode,
    })),
}));
