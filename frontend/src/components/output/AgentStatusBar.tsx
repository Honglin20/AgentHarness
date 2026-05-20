"use client";

import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { Badge } from "@/components/ui/badge";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { STATUS_ICON, STATUS_COLOR, STATUS_PULSE, formatDuration } from "./status-config";

function AgentPill({ node }: { node: NodeState }) {
  const isRunning = node.status === "running";
  const hasError = (node.status === "failed" || node.status === "retrying") && node.error;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant={isRunning ? "default" : "secondary"}
          className={cn(
            "inline-flex h-8 shrink-0 items-center gap-1.5 px-3 text-xs font-medium",
            isRunning && "bg-blue-500/10 text-blue-600 dark:text-blue-400",
            hasError && "cursor-help border-red-300 bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400"
          )}
        >
          <span
            className={cn(
              STATUS_COLOR[node.status],
              STATUS_PULSE[node.status] && "animate-pulse"
            )}
          >
            {STATUS_ICON[node.status]}
          </span>
          <span>{node.name}</span>
          {node.durationMs != null && (
            <span className="text-muted-foreground">
              {formatDuration(node.durationMs)}
            </span>
          )}
        </Badge>
      </TooltipTrigger>
      {hasError && (
        <TooltipContent side="bottom" className="max-w-xs text-xs">
          {node.error}
        </TooltipContent>
      )}
    </Tooltip>
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
