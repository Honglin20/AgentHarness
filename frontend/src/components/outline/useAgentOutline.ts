/**
 * useAgentOutline — React binding for deriveOutlineItems.
 *
 * Subscribes to the scoped workflow / conversation / todo stores and
 * memoizes the derivation. Re-derives ONLY when one of the three inputs
 * changes by reference. Because each store uses immutable updates, this
 * effectively means: re-derive on any store mutation, but skip re-render
 * if the derived array is reference-equal (React.memo on items).
 *
 * Note: useWorkflowStore returns StoreApi | null (no active workflow on
 * the start page). The non-null assertion on the useStore calls matches
 * the convention at ScopedConversationTab.tsx:476 — the surrounding
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

  const nodes = useStore(workflowStoreApi!, (s) => s.nodes);
  const todos = useStore(todoStoreApi!, (s) => s.todos);

  return useMemo(
    () => deriveOutlineItems(nodes, messages, todos),
    [nodes, messages, todos],
  );
}
