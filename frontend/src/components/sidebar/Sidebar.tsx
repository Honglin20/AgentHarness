"use client";

import { Clock, LayoutTemplate, FileText } from "lucide-react";
import { RunHistoryList } from "./RunHistoryList";
import { TemplateLibrary } from "./TemplateLibrary";
import { AgentBrowser } from "./AgentBrowser";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  return (
    <div className="flex h-full flex-col border-r border-app-border bg-white">
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
      <div className="max-h-[30%] overflow-auto">
        <AgentBrowser />
      </div>

      <Separator />
      <div className="flex items-center gap-2 px-3 py-2">
        <LayoutTemplate className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">Templates</span>
      </div>
      <div className="max-h-[40%] overflow-auto">
        <TemplateLibrary />
      </div>
    </div>
  );
}
