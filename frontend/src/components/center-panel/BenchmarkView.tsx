"use client";

import React from "react";
import { useBatchStore } from "@/stores/batchStore";
import { ScopedConversationTab } from "@/components/conversation/ScopedConversationTab";
import { ScopedResultsTab } from "@/components/results/ScopedResultsTab";
import BenchmarkEditor from "@/components/benchmark/BenchmarkEditor";
import BenchmarkRunner from "@/components/benchmark/BenchmarkRunner";
import BenchmarkCompare from "@/components/benchmark/BenchmarkCompare";
import { ErrorBoundary } from "@/components/ErrorBoundary";

type BenchmarkViewMode = "runner" | "compare" | "editor";

interface BenchmarkViewProps {
  benchmarkData: Record<string, unknown>;
  benchmarkName: string;
  onSaveBenchmark: (
    name: string,
    tasks: { label: string; inputs: Record<string, string> }[],
    description: string
  ) => Promise<void>;
  liveResultCount: number;
  batchRunning: boolean;
  chatInput: React.ReactNode;
}

/**
 * Renders the benchmark center-panel view with Run/Compare/Edit tabs
 * and an optional detail sub-view for in-progress batch runs.
 */
export function BenchmarkView({
  benchmarkData,
  benchmarkName,
  onSaveBenchmark,
  liveResultCount,
  batchRunning,
  chatInput,
}: BenchmarkViewProps) {
  const [benchmarkView, setBenchmarkView] = React.useState<BenchmarkViewMode>("runner");
  const [activeTab, setActiveTab] = React.useState<"conversation" | "results">("conversation");

  const benchmarkSelectedRunId = useBatchStore((s) => s.selectedRunId);
  const showBenchmarkDetail = benchmarkView === "runner" && batchRunning && benchmarkSelectedRunId;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-app-bg-primary">
      <div className="flex shrink-0 items-center gap-2 border-b border-app-border px-2 pt-1">
        {/* Benchmark tabs */}
        {(["runner", "compare", "editor"] as const).map((view) => (
          <button
            key={view}
            onClick={() => setBenchmarkView(view)}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              benchmarkView === view
                ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                : "text-muted-foreground hover:text-app-text-primary"
            }`}
          >
            {view === "runner" ? "Run" : view === "compare" ? "Compare" : "Edit"}
          </button>
        ))}
        <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
          BENCHMARK · {benchmarkName}
        </span>

        {/* Detail sub-tabs when a batch run is selected */}
        {showBenchmarkDetail && (
          <>
            <span className="text-muted-foreground">|</span>
            <button
              onClick={() => setActiveTab("conversation")}
              className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === "conversation"
                  ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                  : "text-muted-foreground hover:text-app-text-primary"
              }`}
            >
              Conversation
            </button>
            <button
              onClick={() => setActiveTab("results")}
              className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === "results"
                  ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
                  : "text-muted-foreground hover:text-app-text-primary"
              }`}
            >
              Results{liveResultCount > 0 ? ` ·${liveResultCount}` : ""}
            </button>
            <button
              onClick={() => useBatchStore.getState().selectRun(null)}
              className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground hover:text-app-text-primary"
            >
              Tasks
            </button>
          </>
        )}
      </div>

      <div className="flex-1 overflow-hidden">
        {benchmarkView === "runner" && showBenchmarkDetail && activeTab === "conversation" ? (
          <ErrorBoundary module="ConversationTab">
            <ScopedConversationTab />
          </ErrorBoundary>
        ) : benchmarkView === "runner" && showBenchmarkDetail && activeTab === "results" ? (
          <ErrorBoundary module="ResultsTab">
            <ScopedResultsTab />
          </ErrorBoundary>
        ) : benchmarkView === "runner" ? (
          <ErrorBoundary module="BenchmarkRunner">
            <BenchmarkRunner
              benchmark={
                benchmarkData as {
                  name: string;
                  description?: string;
                  tasks: { id: string; label: string; inputs: Record<string, string> }[];
                }
              }
              onBack={() => setBenchmarkView("compare")}
            />
          </ErrorBoundary>
        ) : benchmarkView === "compare" ? (
          <ErrorBoundary module="BenchmarkCompare">
            <BenchmarkCompare benchmarkName={benchmarkName} />
          </ErrorBoundary>
        ) : benchmarkView === "editor" ? (
          <ErrorBoundary module="BenchmarkEditor">
            <BenchmarkEditor
              initialName={benchmarkName}
              initialTasks={
                ((benchmarkData as Record<string, unknown>).tasks as {
                  label: string;
                  inputs: Record<string, string>;
                }[]) ?? []
              }
              initialDescription={((benchmarkData as Record<string, unknown>).description as string) ?? ""}
              onSave={onSaveBenchmark}
            />
          </ErrorBoundary>
        ) : null}
      </div>

      {batchRunning && <div className="shrink-0">{chatInput}</div>}
    </div>
  );
}
