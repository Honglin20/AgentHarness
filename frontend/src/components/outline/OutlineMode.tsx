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
 *
 * Selection is per-agent (nodeId); the iter shown is decided inside
 * AgentDetailView (defaults to latestIter, switchable via dropdown).
 */
export function OutlineMode() {
  const groups = useAgentOutline();
  const selectedNodeId = useOutlineStore((s) => s.selectedNodeId);

  const selected = useMemo(
    () => groups.find((g) => g.nodeId === selectedNodeId) ?? null,
    [groups, selectedNodeId],
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
            latestIteration={selected.latestIteration}
            iterCount={selected.iterCount}
            iters={selected.iters}
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
