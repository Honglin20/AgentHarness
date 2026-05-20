"use client";

import { useWorkflowStore } from "@/stores/workflowStore";
import AgentStatusBar from "@/components/output/AgentStatusBar";
import StreamingText from "@/components/output/StreamingText";
import WorkflowLauncher from "@/components/output/WorkflowLauncher";

export function CenterPanel() {
  const status = useWorkflowStore((s) => s.status);
  const nodeCount = useWorkflowStore((s) => Object.keys(s.nodes).length);
  const isIdle = status === "idle" && nodeCount === 0;

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary">
      {isIdle ? (
        <WorkflowLauncher />
      ) : (
        <>
          <AgentStatusBar />
          <StreamingText />
        </>
      )}
    </div>
  );
}
