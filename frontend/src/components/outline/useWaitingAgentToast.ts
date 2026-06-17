/**
 * useWaitingAgentToast — fire a toast the first time a NEW pending question
 * appears on any agent. Independent of autoFollow.
 *
 * Identity for "new": the questionId carried on the waiting agent's latest
 * activity. Each ask_user call generates a fresh questionId, so two
 * consecutive asks by the same agent both produce toasts. Falls back to
 * `${group.nodeId}__iter${n}` if questionId is missing (engine regression
 * guard — see Decision 2 in docs/plans/2026-06-12-outline-toast-hook-split.md).
 *
 * Folding (2026-06-17): consumes OutlineGroup[]; checks group.latest for
 * waiting-for-user. Only the latest iter of a node can be waiting, so this
 * is equivalent to scanning per-iter items.
 */

"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { OutlineGroup } from "./types";

export function useWaitingAgentToast(groups: OutlineGroup[]): void {
  const prevQuestionIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Multi-waiting priority: groups are sorted by first-appearance order
    // ascending, so find() returns the earliest-waiting agent.
    const waiting = groups.find((g) => g.latest.status === "waiting-for-user");

    const currentQuestionId = waiting?.latest.activity.kind === "waiting-for-user"
      ? (waiting.latest.activity.questionId || `__no_qid__${waiting.nodeId}__iter${waiting.latestIteration}`)
      : null;

    if (currentQuestionId && prevQuestionIdRef.current !== currentQuestionId) {
      toast.info(`${waiting!.name} is waiting for your answer`, {
        description: "Click the highlighted agent in the outline to respond.",
        duration: 8000,
      });
    }
    prevQuestionIdRef.current = currentQuestionId;
  }, [groups]);
}
