"use client";

import { useState, useEffect, useCallback } from "react";
import { Clock, FileText, Plus, GitCompare, FlaskConical } from "lucide-react";
import { RunHistoryList } from "./RunHistoryList";
import { AgentBrowser } from "./AgentBrowser";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { useResetWorkflow } from "@/hooks/useResetWorkflow";
import { WorkflowCompareDialog } from "@/components/compare/WorkflowCompareDialog";
import { fetchWithAuth } from "@/lib/api";

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

export function Sidebar({ onSelectBenchmark, selectedBenchmark, onLeaveBenchmark }: Props) {
  const resetWorkflow = useResetWorkflow();
  const [compareOpen, setCompareOpen] = useState(false);
  const [benchmarks, setBenchmarks] = useState<BenchmarkItem[]>([]);

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

      {/* Benchmarks section */}
      {benchmarks.length > 0 && (
        <>
          <div className="flex items-center gap-2 px-3 py-2">
            <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-app-text-primary">Benchmarks</span>
          </div>
          <div className="max-h-[30%] overflow-auto px-1">
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

      <div className="flex items-center gap-2 px-3 py-2">
        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">History</span>
      </div>
      <div className="flex-1 overflow-hidden">
        <RunHistoryList onLeaveBenchmark={onLeaveBenchmark} />
      </div>

      <Separator />
      <div className="flex items-center gap-2 px-3 py-2">
        <FileText className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">Agents</span>
      </div>
      <div className="max-h-[40%] overflow-auto">
        <AgentBrowser />
      </div>

      <Separator />
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
