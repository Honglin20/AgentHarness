/**
 * useAutoFollowSelection — when autoFollow is on and a new "running" or
 * "waiting-for-user" agent appears, automatically select it.
 *
 * Selection priority (highest first):
 *   1. waiting-for-user  — never miss an ask_user
 *   2. running           — follow active work
 *   3. (no auto-select for completed/failed/idle)
 *
 * When autoFollow is off, this hook does nothing — user's manual selection
 * sticks.
 *
 * Folding (2026-06-17): the hook now consumes OutlineGroup[] instead of
 * per-iter OutlineItem[]. Status lookups go through `group.latest`, which
 * is always the highest iter — historical iters can never be "running" or
 * "waiting" (they're sealed), so semantics are unchanged.
 *
 * Toast notifications for waiting agents live in useWaitingAgentToast
 * (split out so this hook has a single responsibility and so toast behavior
 * is independent of the autoFollow switch).
 */

"use client";

import { useEffect } from "react";
import { useOutlineStore } from "./outlineStore";
import type { OutlineGroup } from "./types";

export function useAutoFollowSelection(groups: OutlineGroup[]): void {
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const select = useOutlineStore((s) => s.select);
  const selectedNodeId = useOutlineStore((s) => s.selectedNodeId);

  useEffect(() => {
    if (!autoFollow) return;

    // Priority 1: any waiting-for-user agent.
    const waiting = groups.find((g) => g.latest.status === "waiting-for-user");
    if (waiting) {
      if (selectedNodeId !== waiting.nodeId) select(waiting.nodeId, true);
      return;
    }

    // Priority 2: the most-recently-started running agent.
    const running = groups
      .filter((g) => g.latest.status === "running")
      .sort((a, b) => b.order - a.order)[0];
    if (running && selectedNodeId !== running.nodeId) {
      select(running.nodeId, true);
    }
  }, [groups, autoFollow, selectedNodeId, select]);
}
