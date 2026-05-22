"use client";

import { useState } from "react";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

interface ToolCallGroupProps {
  tools: ConversationMessage[];
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

function previewArgs(args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return truncate(args, 60);
  if (typeof args !== "object") return truncate(String(args), 60);
  try {
    const entries = Object.entries(args as Record<string, unknown>);
    if (entries.length === 0) return "";
    const parts = entries.map(([k, v]) => {
      const valStr = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${truncate(valStr ?? "", 40)}`;
    });
    return truncate(parts.join(", "), 80);
  } catch {
    return truncate(JSON.stringify(args), 60);
  }
}

function formatBlock(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

/** Single tool call row — always starts collapsed. */
function ToolRow({ message }: { message: ConversationMessage }) {
  const [open, setOpen] = useState(false);
  const { toolName, toolArgs, toolResult } = message;
  const argsPreview = previewArgs(toolArgs);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-muted/50">
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
        <span className="font-medium">{toolName}</span>
        {argsPreview && (
          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
            {argsPreview}
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-5 rounded border border-app-border bg-gray-50 p-2 text-xs">
          {toolArgs != null && (
            <div className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Args</div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{formatBlock(toolArgs)}</pre>
            </div>
          )}
          {toolResult !== undefined && (
            <div>
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Result</div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{formatBlock(toolResult)}</pre>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ToolCallGroup({ tools }: ToolCallGroupProps) {
  const [open, setOpen] = useState(false);

  // Single tool — no group wrapper needed
  if (tools.length === 1) {
    return (
      <div className="ml-4">
        <ToolRow message={tools[0]} />
      </div>
    );
  }

  return (
    <div className="ml-4">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md bg-muted/50 px-2.5 py-1.5 text-left text-xs hover:bg-muted">
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="font-medium">
            Ran {tools.length} tools
          </span>
          {!open && (
            <span className="min-w-0 truncate text-[11px] text-muted-foreground">
              {tools.map((t) => t.toolName).join(" · ")}
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