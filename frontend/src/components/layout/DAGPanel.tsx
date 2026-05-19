"use client";

import { GitBranch } from "lucide-react";
import DAGCanvas from "@/components/dag/DAGCanvas";

export function DAGPanel() {
  return (
    <aside className="flex w-[280px] flex-col border-r border-app-border bg-app-bg-secondary">
      <div className="flex items-center gap-2 border-b border-app-border px-3 py-2">
        <GitBranch className="h-4 w-4 text-app-text-secondary" />
        <span className="text-sm font-medium text-app-text-primary">
          Workflow
        </span>
      </div>
      <div className="flex-1 overflow-hidden">
        <DAGCanvas />
      </div>
    </aside>
  );
}
