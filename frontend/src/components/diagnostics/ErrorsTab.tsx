"use client";

import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AlertCircle } from "lucide-react";

export interface CircularWarning {
  nodeId: string;
  agentName: string;
  message: string;
  lastTool: string | null;
}

export default function ErrorsTab({
  nodes: nodesProp,
  circularWarnings,
}: {
  nodes?: Record<string, NodeState>;
  circularWarnings?: CircularWarning[];
} = {}) {
  const storeNodes = useWorkflowStore((s) => s.nodes);
  const nodes = nodesProp ?? storeNodes;

  const failedNodes = Object.values(nodes).filter(
    (n) => n.status === "failed" || n.status === "retrying"
  );

  if (failedNodes.length === 0 && (!circularWarnings || circularWarnings.length === 0)) {
    return (
      <div className="flex items-center justify-center p-6 text-xs text-muted-foreground">
        No errors
      </div>
    );
  }

  return (
    <>
      {failedNodes.length > 0 && (
        <ScrollArea className="max-h-[calc(100vh-200px)]">
          <div className="divide-y divide-app-border">
            {failedNodes.map((node) => (
              <div key={node.id} className="px-3 py-3">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  <span className="text-sm font-medium text-app-text-primary">
                    {node.name}
                  </span>
                  {node.errorType && (
                    <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-mono text-red-700">
                      {node.errorType}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {node.status === "retrying" ? `Retry #${node.attempt}` : "Failed"}
                  </span>
                </div>
                {node.error && (
                  <pre className="mt-1.5 overflow-x-auto rounded bg-destructive/10 p-2 text-xs text-destructive font-mono">
                    {node.error}
                  </pre>
                )}
                {node.durationMs != null && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    After {node.durationMs < 1000 ? `${node.durationMs}ms` : `${(node.durationMs / 1000).toFixed(1)}s`}
                    {node.willRetry && " · will retry"}
                  </div>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
      {circularWarnings && circularWarnings.length > 0 && (
        <div className="border-t border-app-border">
          <div className="px-3 py-2 text-xs font-medium text-amber-600">Circular Warnings</div>
          {circularWarnings.map((w, i) => (
            <div key={i} className="px-3 py-2 border-t border-app-border">
              <div className="flex items-center gap-2">
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-mono text-amber-700">
                  Circular
                </span>
                <span className="text-sm font-medium text-app-text-primary">
                  {w.agentName || w.nodeId}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{w.message}</p>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
