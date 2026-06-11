"use client";

import React, { useMemo } from "react";
import { AgentOutline } from "./AgentOutline";
import { AgentDetailView } from "./AgentDetailView";
import { useOutlineStore } from "./outlineStore";
import { useAgentOutline } from "./useAgentOutline";

/**
 * OutlineMode — split layout: outline (~240px) + detail (fills rest).
 *
 * If no selection and autoFollow didn't pick anything yet, show a hint
 * in the detail pane instead of an empty NodeBlockCard.
 */
export function OutlineMode() {
  const items = useAgentOutline();
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  const selected = useMemo(
    () => items.find((i) => i.key === selectedKey) ?? null,
    [items, selectedKey],
  );

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-60 shrink-0 border-r border-app-border bg-app-bg-primary">
        <AgentOutline />
      </aside>
      <div className="min-w-0 flex-1">
        {selected ? (
          <AgentDetailView
            nodeId={selected.nodeId}
            iteration={selected.iteration}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select an agent on the left to view its conversation.
          </div>
        )}
      </div>
    </div>
  );
}
