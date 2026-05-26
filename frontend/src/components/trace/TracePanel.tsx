"use client";

import { useWorkflowStore } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
  retrying: "Retrying",
};

export default function TracePanel() {
  const nodes = useWorkflowStore((s) => s.nodes);
  const status = useWorkflowStore((s) => s.status);

  const nodeList = Object.values(nodes);
  if (nodeList.length === 0) return null;

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
    <div className="flex flex-col border-t border-app-border">
      <div className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-app-text-secondary">
        Trace
      </div>
      <ScrollArea className="max-h-[300px]">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="px-2 py-1 text-xs">Agent</TableHead>
              <TableHead className="px-2 py-1 text-xs">Status</TableHead>
              <TableHead className="px-2 py-1 text-xs text-right">Time</TableHead>
              <TableHead className="px-2 py-1 text-xs text-right">In</TableHead>
              <TableHead className="px-2 py-1 text-xs text-right">Out</TableHead>
              <TableHead className="px-2 py-1 text-xs text-right">Total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {nodeList.map((node) => (
              <TableRow key={node.id}>
                <TableCell className="px-2 py-1 font-medium">
                  {node.name}
                </TableCell>
                <TableCell className="px-2 py-1 text-muted-foreground">
                  {STATUS_LABEL[node.status] || node.status}
                </TableCell>
                <TableCell className="px-2 py-1 text-right text-muted-foreground">
                  {formatDuration(node.durationMs)}
                </TableCell>
                <TableCell className="px-2 py-1 text-right text-muted-foreground">
                  {formatTokens(node.tokenUsage?.input)}
                </TableCell>
                <TableCell className="px-2 py-1 text-right text-muted-foreground">
                  {formatTokens(node.tokenUsage?.output)}
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
