"use client";

import { ChevronRight } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import { formatDuration } from "@/components/output/status-config";
import { MarkdownText } from "./MarkdownText";

interface AgentMessageProps {
  message: ConversationMessage;
  /** Whether the surrounding agent section is collapsed (controlled). */
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** Total items in the section (text + N tool calls), shown in the collapsed header. */
  sectionItemCount: number;
}

const AGENT_STATUS_BADGE_BG: Record<string, string> = {
  streaming: "bg-blue-500/10 text-blue-500",
  done: "bg-emerald-500/10 text-emerald-500",
  error: "bg-red-500/10 text-red-500",
};

function firstNonEmptyLine(s: string): string {
  for (const line of s.split("\n")) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}

export function AgentMessage({ message, collapsed, onToggleCollapse, sectionItemCount }: AgentMessageProps) {
  const { agentName, content, status, durationMs } = message;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;
  const isStreaming = status === "streaming";

  const text = content ?? "";
  const preview = firstNonEmptyLine(text);
  const lineCount = text.split("\n").length;
  const hasMore = lineCount > 1 || text.length > preview.length || sectionItemCount > 1;
  const showCollapsed = collapsed && !isStreaming;

  return (
    <div className="flex flex-col gap-1 py-1">
      <div className="flex items-center gap-2">
        {agentName && (
          <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
            {agentName}
          </span>
        )}
        {durationMs != null && (
          <span className="text-xs text-muted-foreground">{formatDuration(durationMs)}</span>
        )}
        {!isStreaming && hasMore && (
          <button
            type="button"
            onClick={onToggleCollapse}
            className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand agent section" : "Collapse agent section"}
          >
            <ChevronRight
              className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-90"}`}
            />
            {collapsed
              ? sectionItemCount > 1
                ? `Show (${sectionItemCount} items)`
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
          className="truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
          title="Click to expand"
        >
          {preview || "(empty output)"}
        </button>
      ) : (
        <div className="text-sm">
          <MarkdownText>{text}</MarkdownText>
          {isStreaming && <span className="animate-pulse">▎</span>}
        </div>
      )}
    </div>
  );
}
