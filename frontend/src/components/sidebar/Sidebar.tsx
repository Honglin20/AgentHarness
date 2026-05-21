"use client";

import { useState } from "react";
import { Clock, FileText, Plus, GitCompare } from "lucide-react";
import { RunHistoryList } from "./RunHistoryList";
import { AgentBrowser } from "./AgentBrowser";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { useResetWorkflow } from "@/hooks/useResetWorkflow";
import { WorkflowCompareDialog } from "@/components/compare/WorkflowCompareDialog";

export function Sidebar() {
  const resetWorkflow = useResetWorkflow();
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <div className="flex h-full flex-col border-r border-app-border bg-white">
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

      <div className="flex items-center gap-2 px-3 py-2">
        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">History</span>
      </div>
      <div className="flex-1 overflow-hidden">
        <RunHistoryList />
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
