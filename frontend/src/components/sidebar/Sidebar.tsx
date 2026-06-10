"use client";

import React, { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import {
  Clock,
  FileText,
  Plus,
  GitCompare,
  FlaskConical,
  CheckSquare,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { RunHistoryList } from "./RunHistoryList";
import { AgentBrowser } from "./AgentBrowser";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { useResetWorkflow } from "@/hooks/useResetWorkflow";
import { fetchWithAuth } from "@/lib/api";
import { useRunHistoryStore } from "@/stores/runHistoryStore";

// Compare dialog is a heavy modal opened on demand — defer its chunk so the
// sidebar doesn't ship it on first paint.
const WorkflowCompareDialog = dynamic(
  () => import("@/components/compare/WorkflowCompareDialog").then((m) => m.WorkflowCompareDialog),
  { ssr: false },
);

interface BenchmarkItem {
  name: string;
  description?: string;
  tasks: { id: string; label: string }[];
}

interface Props {
  onSelectBenchmark?: (name: string) => void;
  selectedBenchmark?: string | null;
  onLeaveBenchmark?: () => void;
}

// Sidebar collapse state is local UI — doesn't belong in a global store — but
// the user's preferred layout (e.g. always keep Agents folded) is worth
// remembering across reloads. Guarded for SSR / disabled storage.
function usePersistentBoolean(key: string, defaultValue: boolean) {
  const [value, setValue] = useState<boolean>(() => {
    if (typeof window === "undefined") return defaultValue;
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? defaultValue : stored === "true";
    } catch {
      return defaultValue;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, String(value));
    } catch {
      // localStorage may throw in private mode / disabled storage — non-fatal.
    }
  }, [key, value]);
  return [value, setValue] as const;
}

interface SectionHeaderProps {
  icon: React.ReactNode;
  title: string;
  count?: number;
  expanded: boolean;
  onToggle: () => void;
  action?: React.ReactNode;
  panelId?: string;
}

function SectionHeader({ icon, title, count, expanded, onToggle, action, panelId }: SectionHeaderProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-controls={panelId}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      className="flex cursor-pointer select-none items-center gap-1.5 rounded-md px-2 py-1.5 transition-colors hover:bg-muted/50"
    >
      <span className="shrink-0 text-muted-foreground">
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </span>
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      <span className="text-xs font-semibold text-app-text-primary">{title}</span>
      {count !== undefined && count > 0 && (
        <span className="rounded-full bg-muted px-1.5 text-[10px] font-medium leading-4 text-muted-foreground">
          {count}
        </span>
      )}
      {action && (
        <div onClick={(e) => e.stopPropagation()} className="ml-auto">
          {action}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ onSelectBenchmark, selectedBenchmark, onLeaveBenchmark }: Props) {
  const resetWorkflow = useResetWorkflow();
  const [compareOpen, setCompareOpen] = useState(false);
  const [benchmarks, setBenchmarks] = useState<BenchmarkItem[]>([]);
  const runs = useRunHistoryStore((s) => s.runs);
  const isSelectMode = useRunHistoryStore((s) => s.isSelectMode);
  const toggleSelectMode = useRunHistoryStore((s) => s.toggleSelectMode);

  const [benchmarksOpen, setBenchmarksOpen] = usePersistentBoolean("sidebar.benchmarksOpen", true);
  const [historyOpen, setHistoryOpen] = usePersistentBoolean("sidebar.historyOpen", true);
  const [agentsOpen, setAgentsOpen] = usePersistentBoolean("sidebar.agentsOpen", false);

  useEffect(() => {
    fetchWithAuth("/api/benchmarks")
      .then((r) => r.json())
      .then((data: BenchmarkItem[]) => setBenchmarks(data))
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-full flex-col border-r border-app-border bg-background">
      <div className="px-2 pt-2 pb-1">
        <Button
          size="sm"
          variant="outline"
          onClick={resetWorkflow}
          className="h-8 w-full justify-start gap-1.5 text-xs"
        >
          <Plus className="h-3.5 w-3.5" />
          New Workflow
        </Button>
      </div>

      {/* Benchmarks — capped small so History keeps the lion's share.
          Separator lives inside the expanded branch: a folded section shows
          only its header, no orphan divider line. */}
      {benchmarks.length > 0 && (
        <>
          <SectionHeader
            icon={<FlaskConical className="h-3.5 w-3.5" />}
            title="Benchmarks"
            count={benchmarks.length}
            expanded={benchmarksOpen}
            onToggle={() => setBenchmarksOpen((v) => !v)}
            panelId="sidebar-benchmarks-panel"
          />
          {benchmarksOpen && (
            <>
              <div id="sidebar-benchmarks-panel" className="max-h-[20%] overflow-auto px-1 pb-1">
                {benchmarks.map((bm) => (
                  <button
                    key={bm.name}
                    onClick={() => onSelectBenchmark?.(bm.name)}
                    className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
                      selectedBenchmark === bm.name
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-app-text-primary"
                    }`}
                  >
                    <FlaskConical className="h-3 w-3 shrink-0" />
                    <span className="flex-1 truncate">{bm.name}</span>
                    <span className="text-[10px] opacity-60">{bm.tasks.length}</span>
                  </button>
                ))}
              </div>
              <Separator />
            </>
          )}
        </>
      )}

      {/* History — flex-1 makes it the dominant region. The panel div always
          renders (collapsed = empty flex-1 spacer) so aria-controls stays
          valid and Compare Workflows stays pinned to the bottom instead of
          jumping up under Agents. */}
      <SectionHeader
        icon={<Clock className="h-3.5 w-3.5" />}
        title="History"
        count={runs.length}
        expanded={historyOpen}
        onToggle={() => setHistoryOpen((v) => !v)}
        panelId="sidebar-history-panel"
        action={
          !isSelectMode && runs.length > 0 ? (
            <button
              onClick={toggleSelectMode}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              title="Select multiple runs"
            >
              <CheckSquare className="h-3 w-3" />
            </button>
          ) : null
        }
      />
      <div
        id="sidebar-history-panel"
        className={historyOpen ? "min-h-0 flex-1 overflow-hidden" : "flex-1"}
      >
        {historyOpen && <RunHistoryList onLeaveBenchmark={onLeaveBenchmark} />}
      </div>

      <Separator />

      {/* Agents — capped so a long agent list can't squeeze History. Same
          separator pattern as Benchmarks: folded = header only. */}
      <SectionHeader
        icon={<FileText className="h-3.5 w-3.5" />}
        title="Agents"
        expanded={agentsOpen}
        onToggle={() => setAgentsOpen((v) => !v)}
        panelId="sidebar-agents-panel"
      />
      {agentsOpen && (
        <>
          <div id="sidebar-agents-panel" className="max-h-[25%] overflow-auto">
            <AgentBrowser />
          </div>
          <Separator />
        </>
      )}

      <div className="px-2 py-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setCompareOpen(true)}
          className="h-8 w-full justify-start gap-1.5 text-xs text-muted-foreground hover:text-app-text-primary"
        >
          <GitCompare className="h-3.5 w-3.5" />
          Compare Workflows
        </Button>
      </div>

      <WorkflowCompareDialog open={compareOpen} onOpenChange={setCompareOpen} />
    </div>
  );
}
