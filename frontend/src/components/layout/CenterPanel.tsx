"use client";

import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import AgentStatusBar from "@/components/output/AgentStatusBar";
import StreamingText from "@/components/output/StreamingText";
import WorkflowLauncher from "@/components/output/WorkflowLauncher";

export function CenterPanel() {
  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const workflowError = useOutputStore((s) => s.workflowError);
  const isIdle = status === "idle" && nodeCount === 0;

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary">
      {isIdle ? (
        <WorkflowLauncher />
      ) : workflowError ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <p className="text-sm font-medium text-red-500">Workflow Error</p>
          <p className="max-w-md text-center text-xs text-app-text-secondary">
            {workflowError}
          </p>
        </div>
      ) : (
        <>
          <AgentStatusBar />
          <StreamingText />
        </>
      )}
    </div>
  );
}
