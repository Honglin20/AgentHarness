"use client";

import React from "react";
import type { OutlineItem, OutlineStatus } from "./types";

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
  item: OutlineItem;
  selected: boolean;
  onSelect: (key: string) => void;
}

export const OutlineItemRow = React.memo(function OutlineItemRow({ item, selected, onSelect }: Props) {
  const subtitle = computeSubtitle(item);
  const waiting = item.status === "waiting-for-user";

  return (
    <button
      type="button"
      onClick={() => onSelect(item.key)}
      className={[
        "group flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs transition-colors",
        selected ? "bg-blue-50 dark:bg-blue-900/30 border-l-2 border-blue-500" : "hover:bg-muted/50",
        STATUS_ROW_TONE[item.status],
      ].join(" ")}
      aria-current={selected ? "true" : undefined}
    >
      <span
        aria-hidden
        className={[
          "mt-0.5 shrink-0 text-sm leading-none",
          STATUS_TONE[item.status],
          waiting ? "animate-pulse" : "",
        ].join(" ")}
      >
        {STATUS_ICON[item.status]}
      </span>

      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1.5">
          <span className={`truncate font-medium ${selected ? "text-app-text-primary" : "text-app-text-secondary"}`}>
            {item.name}
          </span>
          {item.badges.map((b, i) => (
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

function computeSubtitle(item: OutlineItem): string | null {
  switch (item.activity.kind) {
    case "running":
      return item.activity.currentStepContent ?? "Working…";
    case "waiting-for-user":
      return `Waiting for answer (${item.activity.questionCount})`;
    case "retrying":
      return `Retrying — ${item.activity.attempt}/${item.activity.maxAttempts}`;
    case "failed":
      return item.activity.errorSummary;
    case "completed":
      return item.activity.durationMs ? `${(item.activity.durationMs / 1000).toFixed(1)}s` : null;
    default:
      return null;
  }
}
