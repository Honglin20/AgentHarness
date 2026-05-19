import { GitBranch } from "lucide-react";

export function DAGPanel() {
  return (
    <aside className="flex w-[280px] flex-col border-r bg-app-bg-secondary">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <GitBranch className="h-4 w-4 text-app-text-secondary" />
        <span className="text-sm font-medium text-app-text-primary">Workflow</span>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-app-text-secondary">DAG visualization</p>
      </div>
    </aside>
  );
}
