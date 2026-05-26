import type { NodeState } from "@/stores/workflowStore";

export const STATUS_ICON: Record<NodeState["status"], string> = {
  idle: "○",
  running: "◉",
  success: "✓",
  failed: "✗",
  retrying: "↻",
};

export const STATUS_COLOR: Record<NodeState["status"], string> = {
  idle: "text-muted-foreground",
  running: "text-blue-500",
  success: "text-emerald-500",
  failed: "text-red-500",
  retrying: "text-amber-500",
};

export const STATUS_PULSE: Record<NodeState["status"], boolean> = {
  idle: false,
  running: true,
  success: false,
  failed: false,
  retrying: false,
};

export function formatDuration(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
