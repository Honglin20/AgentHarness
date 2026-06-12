"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronRight, FileInput, FileOutput, Coins, Wrench } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { ToolBrief } from "@/types/events";

import { formatDuration } from "@/components/output/status-config";
import { MarkdownText } from "./MarkdownText";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

// ---------------------------------------------------------------------------
// Shared utilities
// ---------------------------------------------------------------------------

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

function formatTokenCount(n?: { input: number; output: number; total: number }): string {
  if (n == null) return "";
  if (n.total >= 1000) return `${(n.total / 1000).toFixed(1)}k`;
  return String(n);
}

function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") return output;

  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    for (const [k, v] of Object.entries(obj)) {
      if (v != null) lines.push(`**${k}:** ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
    }
    if (lines.length > 0) return lines.join("\n\n");
  }

  return JSON.stringify(output, null, 2);
}

// ---------------------------------------------------------------------------
// ToolsBadge
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// ThinkingBlock — collapsible reasoning/thinking display
// ---------------------------------------------------------------------------

export function ThinkingBlock({
  text,
  streaming,
  defaultOpen = false,
}: {
  text: string;
  streaming: boolean;
  /**
   * Initial expanded state. Callers that render ThinkingBlock in response to
   * a user "show thinking" click pass `true` so the user doesn't have to
   * click twice (once to reveal the block, once to expand it). Default
   * `false` preserves the legacy collapsed-on-mount behavior for any caller
   * that hasn't opted in.
   */
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!text) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-md border border-amber-500/20 bg-amber-500/5">
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-2 py-1 text-xs text-amber-600 hover:text-amber-500 transition-colors">
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="font-medium">Thinking</span>
        {streaming && <span className="animate-pulse text-amber-400">...</span>}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t border-amber-500/20 px-2 py-1.5 text-xs text-muted-foreground max-h-64 overflow-y-auto">
          <MarkdownText>{text}</MarkdownText>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// ---------------------------------------------------------------------------
// Shared props type
// ---------------------------------------------------------------------------

type IOTab = "input" | "output";

/** Shared so callers (e.g. ScopedConversationTab.NodeBlockCard) can pass
 *  these through to AgentNodeHeader without redeclaring the shape. */
export type AgentNodeGetAgentIO = (nodeId: string) =>
  | { inputPrompt?: string; outputResult?: unknown; systemPrompt?: string }
  | undefined;
export type AgentNodeGetNodeState = (nodeId: string) =>
  | { tokenUsage?: { input: number; output: number; total: number }; tools?: ToolBrief[]; model?: string }
  | undefined;

interface AgentNodeHeaderProps {
  message: ConversationMessage;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  sectionItemCount?: number;
  getAgentIO?: AgentNodeGetAgentIO;
  getNodeState?: AgentNodeGetNodeState;
}

// ---------------------------------------------------------------------------
// AgentNodeHeader — the top bar of an agent node card
// Renders: agent name badge, duration, tokens, IO buttons, tools badge,
// collapse toggle, and the IO Sheet.
// ---------------------------------------------------------------------------

export function AgentNodeHeader({
  message,
  collapsed,
  onToggleCollapse,
  sectionItemCount,
  getAgentIO,
  getNodeState,
}: AgentNodeHeaderProps) {
  const { agentName, content, status, durationMs, nodeId } = message;
  const isFollowup = message.followup === true;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;
  const isStreaming = status === "streaming";
  const isDone = status === "done";

  const agentIO = nodeId ? getAgentIO?.(nodeId) : undefined;
  const nodeState = nodeId ? getNodeState?.(nodeId) : undefined;
  const hasIO = isDone && agentIO && (agentIO.inputPrompt || agentIO.outputResult != null);
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
  const hasMore = lineCount > 1 || text.length > preview.length || (sectionItemCount ?? 0) > 1;

  return (
    <>
      <div className="flex min-w-0 items-center gap-2">
        {agentName && (
          <span className={`inline-flex max-w-[40%] shrink items-center truncate rounded-md px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
            {agentName}
          </span>
        )}
        {isFollowup && (
          <span className="shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium text-purple-600 bg-purple-500/10">
            追问
          </span>
        )}
        {nodeState?.model && (
          <span className="shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-xs text-muted-foreground bg-muted" title="LLM Model">
            {nodeState.model}
          </span>
        )}
        {durationMs != null && (
          <span className="shrink-0 text-xs text-muted-foreground">{formatDuration(durationMs)}</span>
        )}
        {tokenUsage && tokenUsage.total > 0 && (
          <span className="shrink-0 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs text-amber-600 bg-amber-500/10" title={`${tokenUsage.input} in / ${tokenUsage.output} out`}>
            <Coins className="h-3 w-3" />
            {formatTokenCount(tokenUsage)}
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
        {!isStreaming && hasMore && onToggleCollapse && (
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
              ? sectionItemCount && sectionItemCount > 1
                ? `Show (${sectionItemCount})`
                : `Show ${lineCount} lines`
              : "Collapse"}
          </button>
        )}
      </div>

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
    </>
  );
}

// ---------------------------------------------------------------------------
// AgentMessage — backward-compatible: header + content
// Used by callers that render a single agent message outside a NodeBlock
// (e.g. legacy / non-scoped contexts). ScopedConversationTab uses the
// internal NodeBlockCard + AgentMsgItem path instead.
// ---------------------------------------------------------------------------

interface AgentMessageProps {
  message: ConversationMessage;
  collapsed: boolean;
  onToggleCollapse: () => void;
  sectionItemCount: number;
  getAgentIO?: (nodeId: string) => { inputPrompt?: string; outputResult?: unknown; systemPrompt?: string } | undefined;
  getNodeState?: (nodeId: string) => {
    tokenUsage?: { input: number; output: number; total: number };
    tools?: ToolBrief[];
    model?: string;
    retryAttempts?: import("@/stores/workflowStore").RetryAttempt[];
    classifiedFailure?: import("@/stores/workflowStore").ClassifiedFailure;
  } | undefined;
}

export function AgentMessage({ message, collapsed, onToggleCollapse, sectionItemCount, getAgentIO, getNodeState }: AgentMessageProps) {
  const { content, status, thinking, nodeId } = message;
  const text = content ?? "";
  const isStreaming = status === "streaming";
  const showCollapsed = collapsed && !isStreaming;
  const nodeState = nodeId ? getNodeState?.(nodeId) : undefined;
  const retryAttempts = nodeState?.retryAttempts ?? [];
  const classifiedFailure = nodeState?.classifiedFailure;

  return (
    <div className="flex min-w-0 flex-col gap-1 py-1">
      <AgentNodeHeader
        message={message}
        collapsed={collapsed}
        onToggleCollapse={onToggleCollapse}
        sectionItemCount={sectionItemCount}
        getAgentIO={getAgentIO}
        getNodeState={getNodeState}
      />
      {thinking && (
        <ThinkingBlock text={thinking} streaming={isStreaming} />
      )}
      {/* Retry status lines (PR-D) — accumulate visible above content */}
      {retryAttempts.length > 0 && (
        <div className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
          {retryAttempts.map((r, i) => (
            <div key={`${r.attempt}-${i}`} className="flex items-center gap-1.5">
              <span className="text-amber-500">🔄</span>
              <span>
                Retrying ({r.attempt + 1}/{r.maxAttempts}):{" "}
                <span className="font-medium">{r.category}</span>
                {r.delayS > 0 && ` — sleeping ${r.delayS}s`}
              </span>
            </div>
          ))}
        </div>
      )}
      {/* Final classified failure (PR-D) — inline error card, no toast */}
      {classifiedFailure && (
        <div className="rounded-md border border-red-500/40 bg-red-500/5 px-3 py-2 text-[11px]">
          <div className="flex items-center gap-1.5 text-red-600 dark:text-red-400">
            <span>❌</span>
            <span className="font-medium">
              Failed: {classifiedFailure.category}
              {classifiedFailure.attemptsUsed > 1 && ` after ${classifiedFailure.attemptsUsed} attempts`}
            </span>
          </div>
          <p className="mt-0.5 text-muted-foreground">{classifiedFailure.reason}</p>
          <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">
            {classifiedFailure.errorType}: {classifiedFailure.message}
          </p>
        </div>
      )}
      {status === "error" && !text ? (
        <p className="text-sm text-red-500">An error occurred</p>
      ) : showCollapsed ? (
        <button
          type="button"
          onClick={onToggleCollapse}
          className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
          title="Click to expand"
        >
          {firstNonEmptyLine(text) || "(empty output)"}
        </button>
      ) : (
        <div className="min-w-0 text-sm">
          <MarkdownText>{text}</MarkdownText>
          {isStreaming && <span className="animate-pulse">▎</span>}
        </div>
      )}
    </div>
  );
}
