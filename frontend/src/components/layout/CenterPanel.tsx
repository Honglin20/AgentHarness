import { Activity } from "lucide-react";

export function CenterPanel() {
  return (
    <main className="flex flex-1 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Activity className="h-4 w-4 text-app-text-secondary" />
        <span className="text-sm font-medium text-app-text-primary">Output</span>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-app-text-secondary">Agent output and charts</p>
      </div>
    </main>
  );
}
