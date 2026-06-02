"use client";

import { memo, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { DiffView } from "./DiffView";
import { FileContentView } from "./FileContentView";
import ChartWidget from "@/components/output/ChartWidget";
import type { ChartPayload } from "@/types/events";

interface ToolCallMessageProps {
  message: ConversationMessage;
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

function previewArgs(toolName: string | undefined, args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return truncate(args, 60);
  if (typeof args !== "object") return truncate(String(args), 60);
  try {
    const entries = Object.entries(args as Record<string, unknown>);
    if (entries.length === 0) return "";
    if (toolName === "bash" && entries[0]?.[0] === "command") {
      return "$ " + truncate(String(entries[0][1]), 58);
    }
    if (FILE_TOOLS.has(toolName ?? "") && entries[0]?.[0] === "path") {
      return truncate(String(entries[0][1]), 60);
    }
    if (toolName === "sub_agent" && entries[0]?.[0] === "agent_name") {
      return truncate(String(entries[0][1]), 60);
    }
    if (toolName === "render_chart") {
      const a = args as Record<string, unknown>;
      const ct = typeof a.chart_type === "string" ? a.chart_type : "chart";
      const t = typeof a.title === "string" ? a.title : "";
      return t ? `${ct} | ${truncate(t, 40)}` : ct;
    }
    const parts = entries.map(([k, v]) => {
      const valStr = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${truncate(valStr ?? "", 30)}`;
    });
    return truncate(parts.join(", "), 60);
  } catch {
    return truncate(JSON.stringify(args), 60);
  }
}

function formatArgsBlock(args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return args;
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const FILE_TOOLS = new Set(["write_file", "edit_file", "read_file", "read_text_file"]);

function normalizeArgs(args: unknown): Record<string, unknown> | null {
  if (args == null) return null;
  if (typeof args === "object" && !Array.isArray(args)) return args as Record<string, unknown>;
  if (typeof args === "string") {
    try {
      const p = JSON.parse(args);
      return typeof p === "object" && p !== null ? p : { _raw: args };
    } catch {
      return { _raw: args };
    }
  }
  return null;
}

function getStringArg(args: unknown, key: string): string | undefined {
  const obj = normalizeArgs(args);
  if (!obj) return undefined;
  return obj[key] as string | undefined;
}

function renderToolResult(toolName: string | undefined, toolArgs: unknown, toolResult: string) {
  const name = toolName ?? "";
  const norm = normalizeArgs(toolArgs);
  // If args couldn't be parsed into a meaningful dict, fall through to generic render
  const hasParsedArgs = norm !== null && !("_raw" in norm);

  if (hasParsedArgs && name === "write_file") {
    const path = getStringArg(toolArgs, "path");
    const content = getStringArg(toolArgs, "content") ?? "";
    return <DiffView oldText="" newText={content} fileName={path} mode="create" />;
  }

  if (hasParsedArgs && name === "edit_file") {
    const path = norm?.path as string | undefined;
    const edits = norm?.edits;
    if (Array.isArray(edits) && edits.length > 0) {
      return (
        <div className="space-y-2">
          {edits.map((edit: Record<string, unknown>, i: number) => (
            <DiffView
              key={i}
              oldText={String(edit.oldText ?? "")}
              newText={String(edit.newText ?? "")}
              fileName={i === 0 ? path : undefined}
              mode="edit"
            />
          ))}
        </div>
      );
    }
    const oldStr = getStringArg(toolArgs, "old_string") ?? getStringArg(toolArgs, "oldText") ?? "";
    const newStr = getStringArg(toolArgs, "new_string") ?? getStringArg(toolArgs, "newText") ?? "";
    return <DiffView oldText={oldStr} newText={newStr} fileName={path} mode="edit" />;
  }

  if (name === "read_file" || name === "read_text_file") {
    const path = hasParsedArgs ? getStringArg(toolArgs, "path") : undefined;
    return <FileContentView content={toolResult} filePath={path} />;
  }

  return (
    <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{toolResult}</pre>
  );
}

function ChartInlineResult({ toolArgs }: { toolArgs: unknown }) {
  const norm = normalizeArgs(toolArgs);
  if (!norm) {
    return <pre className="overflow-x-auto whitespace-pre-wrap text-xs">Rendering chart...</pre>;
  }

  const data = norm.data as Record<string, unknown>[] | undefined;
  if (!data || data.length === 0) {
    return <pre className="overflow-x-auto whitespace-pre-wrap text-xs">No chart data</pre>;
  }

  const chart = {
    chart_type: (norm.chart_type as ChartPayload["chart_type"]) ?? "bar",
    data,
    columns: Object.keys(data[0]),
    x: norm.x as string | undefined,
    y: norm.y as string | undefined,
    label: (norm.label as string) ?? "default",
    title: (norm.title as string) ?? "",
    hue: norm.hue as string | undefined,
    size: norm.size as string | undefined,
  };

  return (
    <div className="my-1 w-full max-w-sm rounded border border-app-border bg-background p-2">
      <ChartWidget chart={chart} />
    </div>
  );
}

export const ToolCallMessage = memo(function ToolCallMessage({ message }: ToolCallMessageProps) {
  const { toolName, toolArgs, toolResult, toolStatus, toolDurationMs, toolStreamingOutput } = message;
  const isRunning = toolStatus === "running";
  const isDone = toolStatus === "done";
  const argsPreview = previewArgs(toolName, toolArgs);
  const [open, setOpen] = useState(false);

  const isFileTool = FILE_TOOLS.has(toolName ?? "");
  const hideArgs = isFileTool || toolName === "render_chart";

  return (
    <div className="ml-6 border-l-2 border-muted pl-3">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 rounded px-1 py-1 text-left text-xs hover:bg-muted/50">
          {isRunning ? (
            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-amber-500" />
          ) : isDone ? (
            <Check className="h-3 w-3 shrink-0 text-emerald-500" />
          ) : (
            <span className="h-3 w-3 shrink-0 rounded-full border border-muted-foreground" />
          )}
          <span className="font-medium text-muted-foreground">{toolName}</span>
          {argsPreview && (
            <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
              {argsPreview}
            </span>
          )}
          {isDone && toolDurationMs != null && (
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatDuration(toolDurationMs)}
            </span>
          )}
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {open ? "▲" : "▼"}
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-1 rounded-md border border-app-border bg-muted/30 p-2 text-xs max-h-80 overflow-y-auto">
            {toolArgs != null && !hideArgs && (
              <div className="mb-1.5">
                <div className="mb-0.5 text-xs font-medium text-muted-foreground">Args</div>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs max-h-32 overflow-y-auto">
                  {formatArgsBlock(toolArgs)}
                </pre>
              </div>
            )}
            {isRunning && toolStreamingOutput && (
              <div>
                <div className="mb-0.5 text-xs font-medium text-muted-foreground">Output</div>
                <pre className="overflow-x-auto overflow-y-auto whitespace-pre-wrap text-xs bg-black/5 rounded p-2 max-h-64">
                  {toolStreamingOutput}
                </pre>
              </div>
            )}
            {toolResult !== undefined && toolName !== "render_chart" && (
              <div>
                <div className="mb-0.5 text-xs font-medium text-muted-foreground">Result</div>
                {renderToolResult(toolName, toolArgs, toolResult)}
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
      {toolName === "render_chart" && isDone && (
        <div className="mt-2 min-w-0">
          <ChartInlineResult toolArgs={toolArgs} />
        </div>
      )}
    </div>
  );
});
