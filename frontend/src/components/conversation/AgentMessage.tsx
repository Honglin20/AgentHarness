"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronRight, FileInput, FileOutput, Coins, Wrench } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { ToolBrief } from "@/types/events";
import { useAgentIOStore } from "@/stores/agentIOStore";
import { useWorkflowStore } from "@/stores/workflowStore";
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

function formatTokenCount(n?: number): string {
  if (n == null) return "";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") return output;

  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    if (obj.summary) lines.push(String(obj.summary));
    if (obj.details) lines.push("", String(obj.details));

    // If there are other fields beyond summary/details, render them as a table
    const extra = Object.entries(obj).filter(
      ([k]) => k !== "summary" && k !== "details"
    );
    if (extra.length > 0) {
      lines.push("", "| Field | Value |", "|-------|-------|");
      for (const [k, v] of extra) {
        const val = typeof v === "object" ? JSON.stringify(v) : String(v);
        lines.push(`| ${k} | ${val} |`);
      }
    }
    if (lines.length > 0) return lines.join("\n");
  }

  return JSON.stringify(output, null, 2);
}

type IOTab = "input" | "output";

function ToolsBadge({ tools }: { tools: ToolBrief[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-violet-500 hover:bg-violet-500/10 transition-colors"
      >
        <Wrench className="h-3 w-3" />
        {tools.length > 0 ? `${tools.length} tool${tools.length > 1 ? "s" : ""}` : "no tools"}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-app-border bg-background shadow-lg">
          <div className="px-3 py-2 text-xs font-medium text-muted-foreground border-b border-app-border">
            Available Tools
          </div>
          <div className="max-h-64 overflow-y-auto p-1">
            {tools.map((t) => (
              <div key={t.name} className="flex flex-col gap-0.5 rounded px-2 py-1.5 hover:bg-muted/50">
                <span className="font-mono text-xs font-medium text-app-text-primary">{t.name}</span>
                {t.description && (
                  <span className="text-xs text-muted-foreground leading-snug">{t.description}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function AgentMessage({ message, collapsed, onToggleCollapse, sectionItemCount }: AgentMessageProps) {
  const { agentName, content, status, durationMs, nodeId } = message;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;
  const isStreaming = status === "streaming";
  const isDone = status === "done";

  const agentIO = useAgentIOStore((s) => nodeId ? s.data[nodeId] : undefined);
  const hasIO = isDone && agentIO && (agentIO.inputPrompt || agentIO.outputResult != null);
  const nodeState = useWorkflowStore((s) => nodeId ? s.nodes[nodeId] : undefined);
  const tokenUsage = nodeState?.tokenUsage;
  const tools = nodeState?.tools;

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
        {tokenUsage && tokenUsage.total > 0 && (
          <span className="shrink-0 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs text-amber-600 bg-amber-500/10" title={`${tokenUsage.input} in / ${tokenUsage.output} out`}>
            <Coins className="h-3 w-3" />
            {formatTokenCount(tokenUsage.total)}
          </span>
        )}
        {hasIO && (
          <>
            <button
              type="button"
              onClick={() => openSheet("input")}
              className="shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-blue-500 hover:bg-blue-500/10 transition-colors"
              title="查看输入"
            >
              <FileInput className="h-3.5 w-3.5" />
              <span className="text-xs">In</span>
            </button>
            <button
              type="button"
              onClick={() => openSheet("output")}
              className="shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors"
              title="查看输出"
            >
              <FileOutput className="h-3.5 w-3.5" />
              <span className="text-xs">Out</span>
            </button>
          </>
        )}
        {tools != null && tools.length > 0 && (
          <ToolsBadge tools={tools} />
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
            <div className="mt-4 space-y-3">
              {activeTab === "input" ? (
                <div className="rounded-md border border-app-border bg-muted p-3 space-y-3">
                  {agentIO.systemPrompt && (
                    <div>
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">System</p>
                      <div className="prose prose-sm max-w-none text-xs">
                        <MarkdownText>{agentIO.systemPrompt}</MarkdownText>
                      </div>
                    </div>
                  )}
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">User Context</p>
                    <div className="prose prose-sm max-w-none text-xs">
                      <MarkdownText>{agentIO.inputPrompt || "(empty)"}</MarkdownText>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-md border border-app-border bg-muted p-3">
                  {agentIO.outputResult != null ? (
                    <div className="prose prose-sm max-w-none text-xs">
                      <MarkdownText>{formatOutputAsMd(agentIO.outputResult)}</MarkdownText>
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">(empty)</p>
                  )}
                </div>
              )}
            </div>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}