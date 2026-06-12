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
 * Side effect: emits a toast notification the FIRST time an agent enters
 * waiting-for-user (transition from "no waiting agent" → "some waiting
 * agent"). Re-fires if the waiting agent changes. Does not re-fire while
 * the same agent remains waiting.
 */

"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useOutlineStore } from "./outlineStore";
import type { OutlineItem } from "./types";

export function useAutoFollowSelection(items: OutlineItem[]): void {
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const select = useOutlineStore((s) => s.select);
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  // Track which agent is currently waiting-for-user, so we fire the toast
  // only on transitions (none → some, or some → different-some), not on
  // every render while waiting persists.
  const prevWaitingKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const waiting = items.find((i) => i.status === "waiting-for-user");

    // Toast only on transition into a NEW waiting agent.
    if (waiting && prevWaitingKeyRef.current !== waiting.key) {
      toast.info(`${waiting.name} is waiting for your answer`, {
        description: "Click the highlighted agent in the outline to respond.",
        duration: 8000,
      });
    }
    prevWaitingKeyRef.current = waiting?.key ?? null;

    if (!autoFollow) return;

    // Priority 1: any waiting-for-user item.
    if (waiting) {
      if (selectedKey !== waiting.key) select(waiting.key, true);
      return;
    }

    // Priority 2: the most-recently-started running item.
    const running = items.filter((i) => i.status === "running").sort((a, b) => b.order - a.order)[0];
    if (running && selectedKey !== running.key) {
      select(running.key, true);
    }
  }, [items, autoFollow, selectedKey, select]);
}
