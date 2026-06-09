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

function ProgressBar({ label, current, max, fmt }: {
  label: string;
  current: number;
  max: number;
  fmt: (n: number) => string;
}) {
  const rawPct = (current / max) * 100;
  const pct = Math.min(rawPct, 100);
  const over = current > max;

  return (
    <div className="flex items-center gap-1.5 text-[10px] leading-none">
      <span className="w-10 shrink-0 truncate text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor(rawPct)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`shrink-0 tabular-nums ${over ? "text-red-500 font-medium" : "text-muted-foreground"}`}>
        {fmt(current)}/{fmt(max)}
      </span>
    </div>
  );
}

function BudgetBarInner({ envelope, nodes }: BudgetBarProps) {
  // Per-agent request budget from settings (default 200). Each agent gets its
  // own budget, so the workflow-wide ceiling is requestLimit × nodeCount.
  const requestLimit = useSettingsStore((s) => s.requestLimit);

  // Accumulate metrics from all nodes
  let totalTokens = 0;
  let totalSteps = 0;
  let totalDuration = 0;
  let totalRequests = 0;
  let nodeCount = 0;

  for (const node of Object.values(nodes)) {
    nodeCount += 1;
    if (node.tokenUsage) {
      totalTokens += node.tokenUsage.input + node.tokenUsage.output;
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

  if (!hasMaxTokens && !hasMaxSteps && !hasMaxDuration && !showRequestsBar) return null;

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
        <ProgressBar label="Tokens" current={totalTokens} max={envelope.max_tokens!} fmt={fmtNum} />
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
