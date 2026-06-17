/**
 * Outline type definitions.
 *
 * Design intent: discriminated unions force consumers to narrow before
 * reading variant-specific fields. New lifecycle states (e.g. "paused",
 * "interrupted-by-quota") are added by extending the union — the UI's
 * switch statement will get a TypeScript error pointing at every place
 * that needs updating.
 */

/** What an agent is doing right now, for the subtitle line. */
export type AgentActivity =
  | { kind: "idle" }
  | { kind: "running"; currentStepContent?: string }
  | { kind: "waiting-for-user"; questionId: string; questionCount: number }
  | { kind: "completed"; durationMs?: number }
  | { kind: "failed"; errorSummary: string }
  | { kind: "retrying"; attempt: number; maxAttempts: number };

/** Visual status — drives the icon + color. Decoupled from activity so
 *  the UI can theme consistently (e.g. "retrying" might share amber color
 *  with "waiting-for-user" but with different icons). */
export type OutlineStatus =
  | "idle"
  | "running"
  | "waiting-for-user"
  | "completed"
  | "failed"
  | "retrying";

/** A badge is a composable annotation — array of these renders independently. */
export interface OutlineBadge {
  kind: "retry" | "followup" | "iteration" | "tokens";
  /** Pre-formatted display string, e.g. "2/3", "#2", "1.5k". */
  text: string;
  /** Optional tooltip / title attribute. */
  title?: string;
}

/** A folded view of one nodeId's OutlineItems across all iterations.
 *
 *  Produced by `groupOutlineByNode` at the view layer; the sidebar renders
 *  one `OutlineGroup` per agent instead of one `OutlineItem` per (agent, iter).
 *  `latest` drives the row's status / activity / badges; `iters` feeds the
 *  per-node iter dropdown in the detail panel.
 *
 *  Folding is view-only — sidecar / deriveOutlineItems still emit one item
 *  per iter (cheaper incremental writes + preserves per-iter metadata). */
export interface OutlineGroup {
  nodeId: string;
  /** Display name — taken from the latest iter so renames mid-run surface. */
  name: string;
  /** Highest-iteration item — drives sidebar row rendering. */
  latest: OutlineItem;
  /** Number of iters seen for this nodeId (≥1). */
  iterCount: number;
  /** = latest.iteration. Convenience field for dropdowns / "Iter N (latest)". */
  latestIteration: number;
  /** All iters in ascending iteration order. */
  iters: OutlineItem[];
  /** Earliest (min) order across iters — preserves first-appearance position. */
  order: number;
}

/** One row in the outline list. */
export interface OutlineItem {
  /** Stable key — `${nodeId}__iter${iteration}` for loops, just nodeId otherwise. */
  key: string;
  nodeId: string;
  /** Display name (agent_name). */
  name: string;
  /** Which iteration this entry represents (1 for non-loop runs). */
  iteration: number;
  /** True if this nodeId has executed more than once. Drives the `#N` badge. */
  hasMultipleIterations: boolean;
  /** True if this is the highest iteration seen for this nodeId.
   *  Drives the badge/status degradation policy: latest iter shows node-level
   *  real-time data (tokenUsage / retryAttempts / status from NodeState);
   *  historical iters show inferred values from messages alone. */
  isLatestIter: boolean;
  status: OutlineStatus;
  activity: AgentActivity;
  badges: OutlineBadge[];
  /** Sort order — by first-activity timestamp ascending. */
  order: number;
}
