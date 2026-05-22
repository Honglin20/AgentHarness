"use client";

import { useState } from "react";
import { ChevronRight, FileInput, FileOutput } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import { useAgentIOStore } from "@/stores/agentIOStore";
import { formatDuration } from "@/components/output/status-config";
import { MarkdownText } from "./MarkdownText";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

interface AgentMessageProps {
  message: ConversationMessage;
  collapsed: boolean;
  onToggleCollapse: () => void;
  sectionItemCount: number;
}

const AGENT_STATUS_BADGE_BG: Record<string, string> = {
  streaming: "bg-blue-500/10 text-blue-500",
  done: "bg-emerald-500/10 text-emerald-500",
  error: "bg-red-500/10 text-red-500",
  interrupted: "bg-amber-500/10 text-amber-500",
};

function firstNonEmptyLine(s: string): string {
  for (const line of s.split("\n")) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}

type IOTab = "input" | "output";

export function AgentMessage({ message, collapsed, onToggleCollapse, sectionItemCount }: AgentMessageProps) {
  const { agentName, content, status, durationMs, nodeId } = message;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;
  const isStreaming = status === "streaming";
  const isDone = status === "done";

  const agentIO = useAgentIOStore((s) => nodeId ? s.data[nodeId] : undefined);
  const hasIO = isDone && agentIO && (agentIO.inputPrompt || agentIO.outputResult != null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<IOTab>("input");

  const openSheet = (tab: IOTab) => {
    setActiveTab(tab);
    setSheetOpen(true);
  };

  const text = content ?? "";
  const preview = firstNonEmptyLine(text);
  const lineCount = text.split("\n").length;
  const hasMore = lineCount > 1 || text.length > preview.length || sectionItemCount > 1;
  const showCollapsed = collapsed && !isStreaming;

  return (
    <div className="flex min-w-0 flex-col gap-1 py-1">
      <div className="flex min-w-0 items-center gap-2">
        {agentName && (
          <span className={`inline-flex max-w-[40%] shrink items-center truncate rounded-md px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
            {agentName}
          </span>
        )}
        {durationMs != null && (
          <span className="shrink-0 text-xs text-muted-foreground">{formatDuration(durationMs)}</span>
        )}
        {hasIO && (
          <>
            <button
              type="button"
              onClick={() => openSheet("input")}
              className="shrink-0 inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-muted-foreground hover:text-blue-500 hover:bg-blue-500/10 transition-colors"
              title="查看输入"
            >
              <FileInput className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={() => openSheet("output")}
              className="shrink-0 inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-muted-foreground hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors"
              title="查看输出"
            >
              <FileOutput className="h-3 w-3" />
            </button>
          </>
        )}
        {!isStreaming && hasMore && (
          <button
            type="button"
            onClick={onToggleCollapse}
            className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand agent section" : "Collapse agent section"}
          >
            <ChevronRight
              className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-90"}`}
            />
            {collapsed
              ? sectionItemCount > 1
                ? `Show (${sectionItemCount})`
                : `Show ${lineCount} lines`
              : "Collapse"}
          </button>
        )}
      </div>

      {status === "error" && !text ? (
        <p className="text-sm text-red-500">An error occurred</p>
      ) : showCollapsed ? (
        <button
          type="button"
          onClick={onToggleCollapse}
          className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
          title="Click to expand"
        >
          {preview || "(empty output)"}
        </button>
      ) : (
        <div className="min-w-0 text-sm">
          <MarkdownText>{text}</MarkdownText>
          {isStreaming && <span className="animate-pulse">▎</span>}
        </div>
      )}

      {hasIO && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="right" className="w-[500px] sm:max-w-lg overflow-y-auto">
            <SheetHeader>
              <SheetTitle>
                {activeTab === "input" ? "输入" : "输出"} — {agentName}
              </SheetTitle>
            </SheetHeader>
            <div className="mt-4 rounded-md border border-app-border bg-gray-50 p-3">
              {activeTab === "input" ? (
                <pre className="whitespace-pre-wrap break-words text-xs font-mono text-app-text-primary">
                  {agentIO.inputPrompt || "(empty)"}
                </pre>
              ) : (
                <pre className="whitespace-pre-wrap break-words text-xs font-mono text-app-text-primary">
                  {agentIO.outputResult != null
                    ? JSON.stringify(agentIO.outputResult, null, 2)
                    : "(empty)"}
                </pre>
              )}
            </div>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}