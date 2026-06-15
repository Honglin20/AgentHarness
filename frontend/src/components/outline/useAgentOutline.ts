/**
 * useAgentOutline — React binding for the outline list.
 *
 * Two data sources, picked at runtime:
 *
 *  1. Sidecar store (replay mode): when the backend persists a pre-computed
 *     outline summary (`{run_id}+outline.json`), `applyHydration` populates
 *     the scoped outline store and we render directly from it — O(items),
 *     no scan over the conversation. This is the fast path for switching to
 *     historical runs.
 *
 *  2. Derivation (live mode + fallback): when the sidecar is absent (live
 *     run, legacy run, fetch failure, or computation failure at save time),
 *     the store's `items` stays `null` and we derive from the full
 *     conversation via `deriveOutlineItems`. Live runs always take this path
 *     because the sidecar is only written at workflow-completion.
 *
 * The fallback path is what keeps the outline correct during the live →
 * replay transition window: hydration may not have completed when the
 * component first renders, so we derive from the (possibly still-empty)
 * messages until the sidecar arrives.
 *
 * Note: useWorkflowStore returns StoreApi | null (no active workflow on the
 * start page). The non-null assertion on the useStore calls matches the
 * convention at ScopedConversationTab.tsx:476 — the surrounding
 * WorkflowScope guarantees the store is non-null by the time components
 * consuming outline data render.
 */

"use client";

import { useMemo } from "react";
import { useStore } from "zustand";
import {
  useConversationMessages,
  useWorkflowStore as useScopedStore,
} from "@/contexts/workflow-context";
import { deriveOutlineItems } from "./deriveOutlineItems";
import type { OutlineItem } from "./types";

export function useAgentOutline(): OutlineItem[] {
  const messages = useConversationMessages();
  const workflowStoreApi = useScopedStore("workflow");
  const todoStoreApi = useScopedStore("todo");
  const outlineStoreApi = useScopedStore("outline");

  const nodes = useStore(workflowStoreApi!, (s) => s.nodes);
  const todos = useStore(todoStoreApi!, (s) => s.todos);
  const sidecarItems = useStore(outlineStoreApi!, (s) => s.items);

  return useMemo(() => {
    // Sidecar ready (replay mode + backend wrote outline) → render directly.
    // `sidecarItems === null` means "no sidecar"; an empty array would be a
    // valid sidecar with zero items (e.g. a workflow that hasn't started).
    if (sidecarItems !== null) return sidecarItems;
    // Live mode or fallback — derive from full conversation.
    return deriveOutlineItems(nodes, messages, todos);
  }, [sidecarItems, nodes, messages, todos]);
}
