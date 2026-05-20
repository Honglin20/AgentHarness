"use client";

import { useState, useEffect } from "react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

interface ToolCallMessageProps {
  message: ConversationMessage;
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

export function ToolCallMessage({ message }: ToolCallMessageProps) {
  const { toolName, toolArgs, toolResult } = message;
  const hasResult = toolResult !== undefined;
  const argsPreview = toolArgs ? truncate(JSON.stringify(toolArgs), 50) : "";
  const borderColor = hasResult ? "border-l-emerald-500" : "border-l-amber-500";

  const [open, setOpen] = useState(false);

  // Auto-expand when result arrives
  useEffect(() => {
    if (hasResult) setOpen(true);
  }, [hasResult]);

  return (
    <div className="ml-8">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md border border-l-4 py-1.5 px-3 text-left text-sm hover:bg-muted/50">
          <span>⚙</span>
          <span className="font-medium">{toolName}</span>
          {argsPreview && (
            <span className="text-xs text-muted-foreground">{argsPreview}</span>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            {open ? "▲" : "▼"}
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className={`rounded-md border border-l-4 ${borderColor} bg-muted/30 p-3 text-sm`}>
            {toolArgs && (
              <div className="mb-2">
                <div className="mb-1 text-xs font-medium text-muted-foreground">Args</div>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs">
                  {JSON.stringify(toolArgs, null, 2)}
                </pre>
              </div>
            )}
            {toolResult !== undefined && (
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">Result</div>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs">
                  {toolResult}
                </pre>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
