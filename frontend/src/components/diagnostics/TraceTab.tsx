"use client";

import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { STATUS_ICON, STATUS_COLOR } from "@/components/output/status-config";

function formatDuration(ms?: number): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTokens(n?: number): string {
  if (n == null) return "-";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  running: "Running",
  success: "Done",
  failed: "Failed",
  retrying: "Retry",
};

export default function TraceTab() {
  const nodes = useWorkflowStore((s) => s.nodes);
  const status = useWorkflowStore((s) => s.status);

  const nodeList = Object.values(nodes);
  if (nodeList.length === 0) {
    return (
      <div className="flex items-center justify-center p-6 text-xs text-muted-foreground">
        No trace data yet
      </div>
    );
  }

  const totalTokens = nodeList.reduce(
    (acc, n) => {
      if (n.tokenUsage) {
        acc.input += n.tokenUsage.input;
        acc.output += n.tokenUsage.output;
        acc.total += n.tokenUsage.total;
      }
      return acc;
    },
    { input: 0, output: 0, total: 0 }
  );

  return (
    <div className="flex flex-col">
      <ScrollArea className="max-h-[calc(100vh-200px)]">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="px-2 py-1">Agent</TableHead>
              <TableHead className="px-2 py-1">Status</TableHead>
              <TableHead className="px-2 py-1 text-right">Time</TableHead>
              <TableHead className="px-2 py-1 text-right">Tokens</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {nodeList.map((node) => (
              <TableRow key={node.id}>
                <TableCell className="px-2 py-1 font-medium">
                  <span className={STATUS_COLOR[node.status]}>
                    {STATUS_ICON[node.status]}
                  </span>{" "}
                  {node.name}
                </TableCell>
                <TableCell className="px-2 py-1 text-muted-foreground">
                  {STATUS_LABEL[node.status] || node.status}
                </TableCell>
                <TableCell className="px-2 py-1 text-right text-muted-foreground">
                  {formatDuration(node.durationMs)}
                </TableCell>
                <TableCell className="px-2 py-1 text-right text-muted-foreground">
                  {formatTokens(node.tokenUsage?.total)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ScrollArea>
      {totalTokens.total > 0 && status === "completed" && (
        <div className="flex items-center gap-2 border-t border-app-border px-3 py-1.5 text-xs text-muted-foreground">
          <span>Total:</span>
          <span>{formatTokens(totalTokens.input)} in</span>
          <span>·</span>
          <span>{formatTokens(totalTokens.output)} out</span>
          <span>·</span>
          <span className="font-medium text-app-text-primary">
            {formatTokens(totalTokens.total)} tokens
          </span>
        </div>
      )}
    </div>
  );
}
