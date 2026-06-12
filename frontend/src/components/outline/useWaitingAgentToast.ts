/**
 * useWaitingAgentToast — fire a toast the first time a NEW pending question
 * appears on any outline item. Independent of autoFollow.
 *
 * Identity for "new": the questionId carried on the waiting item's activity.
 * Each ask_user call generates a fresh questionId, so two consecutive asks
 * by the same agent both produce toasts. Falls back to `${item.key}` if
 * questionId is missing (engine regression guard — see Decision 2 in
 * docs/plans/2026-06-12-outline-toast-hook-split.md).
 */

"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { OutlineItem } from "./types";

export function useWaitingAgentToast(items: OutlineItem[]): void {
  const prevQuestionIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Multi-waiting priority: items are sorted by firstTs ascending in
    // deriveOutlineItems, so find() returns the earliest-waiting agent.
    const waiting = items.find((i) => i.status === "waiting-for-user");

    const currentQuestionId = waiting?.activity.kind === "waiting-for-user"
      ? (waiting.activity.questionId || `__no_qid__${waiting.key}`)
      : null;

    if (currentQuestionId && prevQuestionIdRef.current !== currentQuestionId) {
      toast.info(`${waiting!.name} is waiting for your answer`, {
        description: "Click the highlighted agent in the outline to respond.",
        duration: 8000,
      });
    }
    prevQuestionIdRef.current = currentQuestionId;
  }, [items]);
}
