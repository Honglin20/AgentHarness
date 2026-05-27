/**
 * WorkflowCenterPanel - Context architecture + stable WebSocket management.
 *
 * WebSocket lives here (stable parent that never remounts on workflow switch).
 * Events are routed via eventRouter to scoped stores inside WorkflowScope.
 */

"use client";

import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowScope, WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
import { useWorkflowWS } from "@/contexts/workflow-context/useWorkflowWS";
import { ScopedCenterPanel } from "./ScopedCenterPanel";

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);

  if (activeView.type === "replay") {
    return activeView.run.run_id;
  }
  if (selectedRunId) {
    return selectedRunId;
  }
  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // WebSocket managed at this stable level — survives workflow switches
  const wsMethods = useWorkflowWS(activeView.type === "replay" ? null : workflowId);

  // Replay mode or no workflow: fallback to CenterPanel (data from backend API)
  if (activeView.type === "replay" || !workflowId) {
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  // Context architecture with stable WS
  return (
    <WSMethodProvider
      sendAnswer={wsMethods.sendAnswer}
      sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
    >
      <WorkflowScope
        workflowId={workflowId}
        batchId={activeBatchId}
      >
        <ScopedCenterPanel activeBenchmark={activeBenchmark} />
      </WorkflowScope>
    </WSMethodProvider>
  );
}
