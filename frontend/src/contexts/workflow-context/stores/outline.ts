/**
 * Outline sidecar store — holds the pre-computed per-(nodeId, iter) summary
 * fetched from `GET /runs/{id}/outline`.
 *
 * `items === null` means "sidecar not loaded (yet) or absent" — `useAgentOutline`
 * falls back to deriving from the full conversation. Once a sidecar arrives,
 * `items` is set to the (camelCase-cast) OutlineItem[] and the outline renders
 * from it without touching messages.
 *
 * Live runs never populate this store — `loadRunFromPersistedData` is the only
 * writer, and it runs in replay mode only. Live mode reads messages directly.
 */
import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { OutlineItem } from "@/components/outline/types";

export interface OutlineSidecarState {
  /**
   * `null` = sidecar absent / not yet loaded → useAgentOutline falls back to
   * `deriveOutlineItems(nodes, messages, todos)`.
   *
   * `OutlineItem[]` (even if empty) = sidecar loaded → render directly.
   */
  items: OutlineItem[] | null;
  setItems: (items: OutlineItem[] | null) => void;
  reset: () => void;
}

export function createOutlineSidecarStore(
  _workflowId: string,
): StoreApi<OutlineSidecarState> {
  const store = createStore<OutlineSidecarState>()(() => ({
    items: null,
    setItems: (items) => store.setState({ items }),
    reset: () => store.setState({ items: null }),
  }));
  return store;
}
