"use client";

import { useState, useEffect } from "react";
import { Check, Loader2 } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { DiffView } from "./DiffView";
import { FileContentView } from "./FileContentView";

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
    if ((toolName === "read_file" || toolName === "write_file" || toolName === "edit_file") && entries[0]?.[0] === "path") {
      return truncate(String(entries[0][1]), 60);
    }
    if (toolName === "sub_agent" && entries[0]?.[0] === "agent_name") {
      return truncate(String(entries[0][1]), 60);
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

function getStringArg(args: unknown, key: string): string | undefined {
  if (args == null || typeof args !== "object") return undefined;
  return (args as Record<string, unknown>)[key] as string | undefined;
}

function renderToolResult(toolName: string | undefined, toolArgs: unknown, toolResult: string) {
  const name = toolName ?? "";

  if (name === "write_file") {
    const path = getStringArg(toolArgs, "path");
    const content = getStringArg(toolArgs, "content") ?? "";
    return <DiffView oldText="" newText={content} fileName={path} mode="create" />;
  }

  if (name === "edit_file") {
    const path = getStringArg(toolArgs, "path");
    const oldStr = getStringArg(toolArgs, "old_string") ?? "";
    const newStr = getStringArg(toolArgs, "new_string") ?? "";
    return <DiffView oldText={oldStr} newText={newStr} fileName={path} mode="edit" />;
  }

  if (name === "read_file") {
    const path = getStringArg(toolArgs, "path");
    return <FileContentView content={toolResult} filePath={path} />;
  }

  return (
    <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{toolResult}</pre>
  );
}

export function ToolCallMessage({ message }: ToolCallMessageProps) {
  const { toolName, toolArgs, toolResult, toolStatus, toolDurationMs, toolStreamingOutput } = message;
  const isRunning = toolStatus === "running";
  const isDone = toolStatus === "done";
  const argsPreview = previewArgs(toolName, toolArgs);
  const [open, setOpen] = useState(false);

  // Streaming → auto-expand; Done → auto-collapse
  useEffect(() => {
    if (isRunning && toolStreamingOutput) setOpen(true);
  }, [isRunning, toolStreamingOutput]);

  useEffect(() => {
    if (isDone) setOpen(false);
  }, [isDone]);

  const isFileTool = toolName === "write_file" || toolName === "edit_file" || toolName === "read_file";

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
            {toolArgs != null && !isFileTool && (
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
            {toolResult !== undefined && (
              <div>
                <div className="mb-0.5 text-xs font-medium text-muted-foreground">Result</div>
                {renderToolResult(toolName, toolArgs, toolResult)}
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
