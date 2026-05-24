"use client";

import { useState, useEffect } from "react";
import { Check, ChevronDown, ChevronRight, Loader2, Wrench } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { DiffView } from "./DiffView";
import { FileContentView } from "./FileContentView";

interface ToolCallGroupProps {
  tools: ConversationMessage[];
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

function previewArgs(toolName: string | undefined, args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return truncate(args, 80);
  if (typeof args !== "object") return truncate(String(args), 80);
  try {
    const entries = Object.entries(args as Record<string, unknown>);
    if (entries.length === 0) return "";
    if (toolName === "bash" && entries[0]?.[0] === "command") {
      return truncate(String(entries[0][1]), 100);
    }
    if ((toolName === "read_file" || toolName === "write_file" || toolName === "edit_file") && entries[0]?.[0] === "path") {
      return truncate(String(entries[0][1]), 100);
    }
    const parts = entries.map(([k, v]) => {
      const valStr = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${truncate(valStr ?? "", 40)}`;
    });
    return truncate(parts.join(", "), 80);
  } catch {
    return truncate(JSON.stringify(args), 80);
  }
}

function formatBlock(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
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

  return <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{toolResult}</pre>;
}

function ToolRow({ message }: { message: ConversationMessage }) {
  const [open, setOpen] = useState(false);
  const { toolName, toolArgs, toolResult, toolStatus, toolDurationMs, toolStreamingOutput } = message;
  const isRunning = toolStatus === "running";
  const isDone = toolStatus === "done";
  const argsPreview = previewArgs(toolName, toolArgs);
  const isFileTool = toolName === "write_file" || toolName === "edit_file" || toolName === "read_file";

  useEffect(() => {
    if (isDone) setOpen(true);
  }, [isDone]);

  useEffect(() => {
    if (isRunning && toolStreamingOutput && !open) setOpen(true);
  }, [isRunning, toolStreamingOutput, open]);

  return (
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
          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
            {argsPreview}
          </span>
        )}
        {isDone && toolDurationMs != null && (
          <span className="shrink-0 text-[10px] text-muted-foreground">
            {formatDuration(toolDurationMs)}
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1 rounded-md border border-app-border bg-muted/30 p-2 text-xs">
          {toolArgs != null && !isFileTool && (
            <div className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Args</div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{formatBlock(toolArgs)}</pre>
            </div>
          )}
          {isRunning && toolStreamingOutput && (
            <div>
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Output</div>
              <pre className="overflow-x-auto overflow-y-auto whitespace-pre-wrap text-[11px] bg-black/5 rounded p-2 max-h-64">
                {toolStreamingOutput}
              </pre>
            </div>
          )}
          {toolResult !== undefined && (
            <div>
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Result</div>
              {renderToolResult(toolName, toolArgs, toolResult)}
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ToolCallGroup({ tools }: ToolCallGroupProps) {
  const [open, setOpen] = useState(false);
  const anyRunning = tools.some((t) => t.toolStatus === "running");
  const allDone = tools.every((t) => t.toolStatus === "done");
  const totalDuration = tools.reduce((sum, t) => sum + (t.toolDurationMs ?? 0), 0);

  if (tools.length === 1) {
    return (
      <div className="ml-6 border-l-2 border-muted pl-3">
        <ToolRow message={tools[0]} />
      </div>
    );
  }

  return (
    <div className="ml-6 border-l-2 border-muted pl-3">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 rounded px-1 py-1 text-left text-xs hover:bg-muted/50">
          {anyRunning ? (
            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-amber-500" />
          ) : allDone ? (
            <Check className="h-3 w-3 shrink-0 text-emerald-500" />
          ) : (
            <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          <span className="font-medium text-muted-foreground">
            {tools.length} tools
          </span>
          {!open && (
            <span className="min-w-0 truncate text-[11px] text-muted-foreground">
              {tools.map((t) => t.toolName).join(" · ")}
            </span>
          )}
          {allDone && totalDuration > 0 && (
            <span className="shrink-0 text-[10px] text-muted-foreground">
              {formatDuration(totalDuration)}
            </span>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="flex flex-col gap-0.5 py-1">
            {tools.map((t) => (
              <ToolRow key={t.id} message={t} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
