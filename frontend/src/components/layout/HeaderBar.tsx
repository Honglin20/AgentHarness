import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export function HeaderBar() {
  return (
    <header className="flex h-12 items-center justify-between border-b px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-app-text-primary">
          Agent Harness
        </h1>
        <Separator orientation="vertical" className="h-4" />
        <span className="text-sm text-app-text-secondary">
          Untitled Workflow
        </span>
      </div>
      <Button variant="ghost" size="icon">
        <Settings className="h-4 w-4" />
      </Button>
    </header>
  );
}
