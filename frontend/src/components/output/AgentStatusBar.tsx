"use client";

import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { Badge } from "@/components/ui/badge";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<
  NodeState["status"],
  { icon: string; colorClass: string; pulse: boolean }
> = {
  idle: { icon: "○", colorClass: "text-muted-foreground", pulse: false },
  running: { icon: "◉", colorClass: "text-blue-500", pulse: true },
  success: { icon: "✓", colorClass: "text-emerald-500", pulse: false },
  failed: { icon: "✗", colorClass: "text-red-500", pulse: false },
  retrying: { icon: "↻", colorClass: "text-amber-500", pulse: false },
};

function formatDuration(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function AgentPill({ node }: { node: NodeState }) {
  const config = STATUS_CONFIG[node.status];
  const isRunning = node.status === "running";

  return (
    <Badge
      variant={isRunning ? "default" : "secondary"}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 px-3 text-xs font-medium",
        isRunning && "bg-blue-500/10 text-blue-600 dark:text-blue-400"
      )}
    >
      <span
        className={cn(
          config.colorClass,
          config.pulse && "animate-pulse"
        )}
      >
        {config.icon}
      </span>
      <span>{node.name}</span>
      {node.durationMs != null && (
        <span className="text-muted-foreground">
          {formatDuration(node.durationMs)}
        </span>
      )}
    </Badge>
  );
}

export default function AgentStatusBar() {
  const nodes = useWorkflowStore((s) => s.nodes);

  const nodeList = Object.values(nodes);
  if (nodeList.length === 0) return null;

  return (
    <div className="flex h-12 shrink-0 items-center border-b border-app-border bg-app-bg-secondary px-3">
      <ScrollArea className="flex-1">
        <div className="flex items-center gap-2">
          {nodeList.map((node) => (
            <AgentPill key={node.id} node={node} />
          ))}
        </div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  );
}
