"use client";

import React from "react";
import type { OutlineGroup, OutlineStatus, OutlineBadge } from "./types";

const STATUS_ICON: Record<OutlineStatus, string> = {
  idle: "○",
  running: "◐",
  "waiting-for-user": "●",
  completed: "✓",
  failed: "✗",
  retrying: "↻",
};

const STATUS_TONE: Record<OutlineStatus, string> = {
  idle: "text-muted-foreground/50",
  running: "text-blue-500",
  "waiting-for-user": "text-amber-500",
  completed: "text-emerald-500",
  failed: "text-red-500",
  retrying: "text-amber-500",
};

const STATUS_ROW_TONE: Record<OutlineStatus, string> = {
  idle: "",
  running: "",
  "waiting-for-user": "bg-amber-500/5 border-l-2 border-amber-500",
  completed: "",
  failed: "",
  retrying: "",
};

interface Props {
  group: OutlineGroup;
  selected: boolean;
  onSelect: (nodeId: string) => void;
}

/**
 * OutlineGroupRow — one sidebar row per agent (folds N iters).
 *
 * Visual parity with the prior per-iter row: status icon + tone, name, badges,
 * subtitle. Differences from the old OutlineItemRow:
 *   - Renders `group.latest` (highest iter) as the row's status source.
 *   - `⇡N` badge replaces the per-iter `#N` iteration badge (Decision 4 in
 *     the plan). The latest iter's retry / tokens badges still show.
 *   - onClick emits nodeId (not `${nodeId}__iter${n}`) since selection is
 *     per-agent now; iter is chosen inside the detail panel's dropdown.
 */
export const OutlineGroupRow = React.memo(function OutlineGroupRow({ group, selected, onSelect }: Props) {
  const latest = group.latest;
  const subtitle = computeSubtitle(latest.activity);
  const waiting = latest.status === "waiting-for-user";

  // ⇡N replaces #N iteration badge; retry / tokens still come from latest.
  const badges: OutlineBadge[] = [];
  if (group.iterCount > 1) {
    badges.push({
      kind: "iteration",
      text: `⇡${group.iterCount}`,
      title: `${group.iterCount} iterations — latest is iter ${group.latestIteration}`,
    });
  }
  for (const b of latest.badges) {
    if (b.kind === "iteration") continue; // drop per-iter #N badge
    badges.push(b);
  }

  return (
    <button
      type="button"
      onClick={() => onSelect(group.nodeId)}
      className={[
        "group flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs transition-colors",
        selected && !waiting
          ? "bg-blue-50 dark:bg-blue-900/30 border-l-2 border-blue-500"
          : selected
            ? "bg-blue-50 dark:bg-blue-900/30"
            : "hover:bg-muted/50",
        STATUS_ROW_TONE[latest.status],
      ].join(" ")}
      aria-current={selected ? "true" : undefined}
    >
      <span
        aria-hidden
        className={[
          "mt-0.5 shrink-0 text-sm leading-none",
          STATUS_TONE[latest.status],
          waiting ? "animate-pulse" : "",
        ].join(" ")}
      >
        {STATUS_ICON[latest.status]}
      </span>

      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1.5">
          <span className={`truncate font-medium ${selected ? "text-app-text-primary" : "text-app-text-secondary"}`}>
            {group.name}
          </span>
          {badges.map((b, i) => (
            <span
              key={`${b.kind}-${i}`}
              className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
              title={b.title}
            >
              {b.text}
            </span>
          ))}
        </span>
        {subtitle && (
          <span className="truncate text-[11px] text-muted-foreground">{subtitle}</span>
        )}
      </span>
    </button>
  );
});

function computeSubtitle(activity: OutlineGroup["latest"]["activity"]): string | null {
  switch (activity.kind) {
    case "running":
      return activity.currentStepContent ?? "Working…";
    case "waiting-for-user":
      return `Waiting for answer (${activity.questionCount})`;
    case "retrying":
      return `Retrying — ${activity.attempt}/${activity.maxAttempts}`;
    case "failed":
      return activity.errorSummary;
    case "completed":
      return activity.durationMs ? `${(activity.durationMs / 1000).toFixed(1)}s` : null;
    default:
      return null;
  }
}
