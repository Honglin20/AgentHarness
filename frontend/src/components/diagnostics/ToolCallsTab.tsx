"use client";

import { useToolCallStore, type ToolCallRecord } from "@/stores/toolCallStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function truncateArgs(args: Record<string, unknown>, maxLen = 60): string {
  const str = Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
  return str.length > maxLen ? str.slice(0, maxLen) + "..." : str;
}

function truncateResult(result: string | undefined, maxLen = 80): string {
  if (!result) return "...";
  return result.length > maxLen ? result.slice(0, maxLen) + "..." : result;
}

function ToolCallRow({ record }: { record: ToolCallRecord }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-app-border last:border-b-0">
      <button
        className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-app-bg-secondary"
        onClick={() => setOpen(!open)}
      >
        <ChevronRight
          className={cn(
            "mt-0.5 h-3 w-3 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90"
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-app-text-primary">
              {record.toolName}
            </span>
            <span className="text-[10px] text-muted-foreground">
              {record.agentName}
            </span>
            <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
              {formatTime(record.timestamp)}
            </span>
          </div>
          <div className="mt-0.5 truncate text-[11px] text-muted-foreground font-mono">
            {truncateArgs(record.args)}
          </div>
          {record.result !== undefined && (
            <div className="mt-0.5 truncate text-[11px] text-emerald-600 font-mono">
              {truncateResult(record.result)}
            </div>
          )}
        </div>
      </button>
      {open && (
        <div className="space-y-2 border-t border-app-border bg-app-bg-secondary px-3 py-2">
          <div>
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-1">
              Arguments
            </div>
            <pre className="overflow-x-auto rounded bg-white p-2 text-[11px] font-mono">
              {JSON.stringify(record.args, null, 2)}
            </pre>
          </div>
          {record.result !== undefined && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-1">
                Result
              </div>
              <pre className="overflow-x-auto rounded bg-white p-2 text-[11px] font-mono">
                {record.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolCallsTab() {
  const records = useToolCallStore((s) => s.records);
  const order = useToolCallStore((s) => s.order);
  const [filter, setFilter] = useState<string | null>(null);

  const allRecords = order.map((id) => records[id]);
  const nodeIds = Array.from(new Set(allRecords.map((r) => r.nodeId)));
  const filtered = filter ? allRecords.filter((r) => r.nodeId === filter) : allRecords;

  if (allRecords.length === 0) {
    return (
      <div className="flex items-center justify-center p-6 text-xs text-muted-foreground">
        No tool calls yet
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {nodeIds.length > 1 && (
        <div className="flex items-center gap-1 border-b border-app-border px-3 py-1.5">
          <button
            className={cn(
              "rounded px-2 py-0.5 text-[11px]",
              !filter ? "bg-blue-500 text-white" : "text-muted-foreground hover:text-app-text-primary"
            )}
            onClick={() => setFilter(null)}
          >
            All
          </button>
          {nodeIds.map((id) => (
            <button
              key={id}
              className={cn(
                "rounded px-2 py-0.5 text-[11px]",
                filter === id ? "bg-blue-500 text-white" : "text-muted-foreground hover:text-app-text-primary"
              )}
              onClick={() => setFilter(id)}
            >
              {id}
            </button>
          ))}
        </div>
      )}
      <ScrollArea className="max-h-[calc(100vh-200px)]">
        {filtered.map((record) => (
          <ToolCallRow key={record.id} record={record} />
        ))}
      </ScrollArea>
    </div>
  );
}
