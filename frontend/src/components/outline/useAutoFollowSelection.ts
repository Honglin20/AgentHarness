/**
 * useAutoFollowSelection — when autoFollow is on and a new "running" or
 * "waiting-for-user" item appears, automatically select it.
 *
 * Selection priority (highest first):
 *   1. waiting-for-user  — never miss an ask_user
 *   2. running           — follow active work
 *   3. (no auto-select for completed/failed/idle)
 *
 * When autoFollow is off, this hook does nothing — user's manual selection
 * sticks.
 *
 * Toast notifications for waiting agents live in useWaitingAgentToast
 * (split out so this hook has a single responsibility and so toast behavior
 * is independent of the autoFollow switch).
 */

"use client";

import { useEffect } from "react";
import { useOutlineStore } from "./outlineStore";
import type { OutlineItem } from "./types";

export function useAutoFollowSelection(items: OutlineItem[]): void {
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const select = useOutlineStore((s) => s.select);
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  useEffect(() => {
    if (!autoFollow) return;

    // Priority 1: any waiting-for-user item.
    const waiting = items.find((i) => i.status === "waiting-for-user");
    if (waiting) {
      if (selectedKey !== waiting.key) select(waiting.key, true);
      return;
    }

    // Priority 2: the most-recently-started running item.
    const running = items
      .filter((i) => i.status === "running")
      .sort((a, b) => b.order - a.order)[0];
    if (running && selectedKey !== running.key) {
      select(running.key, true);
    }
  }, [items, autoFollow, selectedKey, select]);
}
