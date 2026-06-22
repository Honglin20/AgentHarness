"use client";

import { useStore } from "zustand";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useSettingsStore } from "@/stores/settingsStore";
import type { WorkflowStores } from "@/contexts/workflow-context/types";

// ── Shared rendering ─────────────────────────────────────────────────

interface BudgetBarProps {
  envelope: Record<string, number>;
  nodes: Record<string, import("@/stores/workflowStore").NodeState>;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtDuration(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${ms}ms`;
}

function barColor(pct: number): string {
  if (pct > 100) return "bg-red-500";
  if (pct > 80) return "bg-yellow-500";
  return "bg-muted-foreground/40";
}

function ProgressBar({ label, current, max, fmt, hint, title }: {
  label: string;
  current: number;
  max: number;
  fmt: (n: number) => string;
  hint?: string;
  title?: string;
}) {
  const rawPct = (current / max) * 100;
  const pct = Math.min(rawPct, 100);
  const over = current > max;

  return (
    <div className="flex items-center gap-1.5 text-[10px] leading-none" title={title}>
      <span className="w-10 shrink-0 truncate text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor(rawPct)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`shrink-0 tabular-nums ${over ? "text-red-500 font-medium" : "text-muted-foreground"}`}>
        {fmt(current)}/{fmt(max)}
        {hint && <span className="text-muted-foreground/60 ml-1">{hint}</span>}
      </span>
    </div>
  );
}

function BudgetBarInner({ envelope, nodes }: BudgetBarProps) {
  // Per-agent request budget from settings (default 200). Each agent gets its
  // own budget, so the workflow-wide ceiling is requestLimit × nodeCount.
  const requestLimit = useSettingsStore((s) => s.requestLimit);
  // Model context window (default 200k). Drives the "Window" bar denominator
  // so users see actual context pressure, not the cumulative cost.
  const modelContextLimit = useSettingsStore((s) => s.modelContextLimit);

  // Accumulate metrics from all nodes
  let totalTokens = 0;          // cumulative cost (input + output summed across nodes)
  let totalCacheHit = 0;        // cumulative cache hits — shows how much of totalTokens was free
  let totalSteps = 0;
  let totalDuration = 0;
  let totalRequests = 0;
  let nodeCount = 0;
  // Largest single-request context window observed across all nodes.
  // "Max" not "sum" because each agent has its own message_history; the
  // workflow's context pressure is the worst agent, not the total.
  let maxWindowTokens = 0;
  // Cache-hit portion of the worst-window node. Tracking alongside
  // maxWindowTokens (rather than just any node) keeps the cache hint visually
  // consistent with the bar — user sees "Window 50k/200k (cache 40k)" and
  // immediately understands only 10k was fresh.
  let maxWindowCacheHit = 0;
  // Whether ANY node has reported stage-2 last_* fields. Old runs / pre-stage-2
  // replayed events lack last_*; falling back to cumulative for them would
  // show a misleading 125% red bar (cumulative can be > modelContextLimit).
  // Instead, we hide the Window bar entirely when no node has real last data.
  let anyNodeHasLastUsage = false;

  for (const node of Object.values(nodes)) {
    // Only count nodes that have actually started (status !== "idle") toward
    // the request budget ceiling. Idle nodes haven't consumed their per-agent
    // request_limit yet, so including them would inflate `max` and make the
    // progress bar misleadingly low. Once a node starts, its budget is "in play"
    // for the rest of the run (even after it completes/fails).
    if (node.status === "idle") continue;
    nodeCount += 1;
    if (node.tokenUsage) {
      totalTokens += node.tokenUsage.input + node.tokenUsage.output;
      if (node.tokenUsage.cacheHit) {
        totalCacheHit += node.tokenUsage.cacheHit;
      }
      // Window = most recent single-shot request. Only count when the node
      // has real last_* (stage-2 backend). Without this guard, cumulative
      // usage on old runs would render against modelContextLimit and look
      // like context exploded — the exact panic this stage is meant to fix.
      if (
        node.tokenUsage.lastInput != null &&
        node.tokenUsage.lastOutput != null
      ) {
        anyNodeHasLastUsage = true;
        const window = node.tokenUsage.lastInput + node.tokenUsage.lastOutput;
        // Tie-break: when windows are equal, prefer the one with cache info
        // so the hint stays visible. Strictly greater would silently drop
        // cache data when two nodes have identical window sizes.
        if (window > maxWindowTokens || (window === maxWindowTokens && maxWindowCacheHit === 0)) {
          maxWindowTokens = window;
          maxWindowCacheHit = node.tokenUsage.lastCacheHit ?? 0;
        }
      }
    }
    if (node.toolCallCount) {
      totalSteps += node.toolCallCount;
    }
    if (node.durationMs) {
      totalDuration += node.durationMs;
    }
    if (node.requests) {
      totalRequests += node.requests;
    }
  }

  const hasMaxTokens = envelope.max_tokens != null;
  const hasMaxSteps = envelope.max_steps != null;
  const hasMaxDuration = envelope.max_duration_ms != null;
  // Show Requests bar whenever at least one agent has reported usage (even
  // before any envelope exists) — request budget is a per-agent concept that
  // doesn't depend on the workflow envelope.
  const showRequestsBar = totalRequests > 0 && nodeCount > 0;
  // Show Window bar only when at least one node has reported stage-2 last_*.
  // Old runs without last_* would otherwise show misleading cumulative-against-
  // limit bars.
  const showWindowBar = anyNodeHasLastUsage && maxWindowTokens > 0 && nodeCount > 0;

  if (!hasMaxTokens && !hasMaxSteps && !hasMaxDuration && !showRequestsBar && !showWindowBar) return null;

  return (
    <div className="flex flex-col gap-1 px-2 py-1.5 border-b border-app-border">
      {showRequestsBar && (
        <ProgressBar
          label="Reqs"
          current={totalRequests}
          max={requestLimit * nodeCount}
          fmt={fmtNum}
        />
      )}
      {hasMaxTokens && (
        <ProgressBar
          label="Cost"
          current={totalTokens}
          max={envelope.max_tokens!}
          fmt={fmtNum}
          hint={totalCacheHit > 0 ? `(cache ${fmtNum(totalCacheHit)})` : undefined}
          title="累计消耗 — 所有 LLM 调用 input+output 之和（非当前上下文窗口）"
        />
      )}
      {showWindowBar && (
        <ProgressBar
          label="Window"
          current={maxWindowTokens}
          max={modelContextLimit}
          fmt={fmtNum}
          hint={maxWindowCacheHit > 0 ? `(cache ${fmtNum(maxWindowCacheHit)})` : undefined}
          title="最近一次单次请求的 input+output（model 实际看到的窗口）。cache 部分是已命中、未计费的"
        />
      )}
      {hasMaxSteps && (
        <ProgressBar label="Steps" current={totalSteps} max={envelope.max_steps!} fmt={String} />
      )}
      {hasMaxDuration && (
        <ProgressBar label="Time" current={totalDuration} max={envelope.max_duration_ms!} fmt={fmtDuration} />
      )}
    </div>
  );
}

// ── Scoped version ───────────────────────────────────────────────────

export function BudgetBarScoped({ stores }: { stores: WorkflowStores }) {
  const envelope = useStore(stores.workflow, (s) => s.envelope);
  const nodes = useStore(stores.workflow, (s) => s.nodes);

  if (!envelope) return null;
  return <BudgetBarInner envelope={envelope} nodes={nodes} />;
}

// ── Global version ───────────────────────────────────────────────────

export default function BudgetBar() {
  const envelope = useWorkflowStore((s) => s.envelope);
  const nodes = useWorkflowStore((s) => s.nodes);

  if (!envelope) return null;
  return <BudgetBarInner envelope={envelope} nodes={nodes} />;
}
