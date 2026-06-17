"use client";

import React from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useOutlineStore } from "./outlineStore";
import type { OutlineItem } from "./types";

interface Props {
  nodeId: string;
  latestIteration: number;
  iterCount: number;
  /** OutlineItems for this node, ascending iter. Used to populate the dropdown. */
  iters: OutlineItem[];
}

/**
 * NodeIterSelector — iter dropdown inside the agent detail panel.
 *
 * Single-iter nodes render no trigger (Decision 4 in plan) — the parent
 * AgentDetailView hides the entire sticky bar in that case.
 *
 * Selection lives in outlineStore.selectedIterByNode so the user's per-agent
 * iter choice survives switching to other agents and back (Decision 2).
 * Defaults to latestIteration when the user hasn't picked yet.
 */
export function NodeIterSelector({ nodeId, latestIteration, iterCount, iters }: Props) {
  const selectedIter = useOutlineStore((s) => s.selectedIterByNode[nodeId] ?? latestIteration);
  const selectIter = useOutlineStore((s) => s.selectIter);

  // iters[] is ascending — render newest-first in the dropdown so the
  // most-relevant entries are visible without scrolling.
  const descending = [...iters].sort((a, b) => b.iteration - a.iteration);

  return (
    <Select value={String(selectedIter)} onValueChange={(v) => selectIter(nodeId, Number(v))}>
      <SelectTrigger className="h-7 w-[180px] text-xs">
        <SelectValue>
          Iter {selectedIter}
          {selectedIter === latestIteration && " (latest)"}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {descending.map((it) => (
          <SelectItem key={it.iteration} value={String(it.iteration)}>
            Iter {it.iteration}
            {it.iteration === latestIteration && " (latest)"}
            <span className="ml-1 text-muted-foreground">— {it.status}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
