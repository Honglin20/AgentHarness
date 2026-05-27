/**
 * WorkflowCenterPanel - Context architecture + stable WebSocket management.
 *
 * WebSocket lives here (stable parent that never remounts on workflow switch).
 * Events are routed via eventRouter to scoped stores inside WorkflowScope.
 *
 * Decisions made HERE:
 * - replay mode → legacy CenterPanel (read-only, no WS needed)
 * - no workflowId → legacy CenterPanel (landing page)
 * - batch mode without selected run → legacy CenterPanel (batch overview)
 * - valid workflowId → Context architecture (WSMethodContext + WorkflowScope)
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
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Replay mode: handled by legacy CenterPanel
  if (activeView.type === "replay") {
    return null;
  }

  // Batch mode: only enter Context path when a run is explicitly selected
  if (activeBatchId) {
    return selectedRunId;
  }

  // Normal mode: use the global workflowId
  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);

  // WebSocket managed at this stable level — survives workflow switches
  const wsMethods = useWorkflowWS(workflowId);

  // Replay mode or no active workflow: use legacy CenterPanel
  if (activeView.type === "replay" || !workflowId) {
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  // Context architecture: WS + scoped stores
  return (
    <WSMethodProvider
      sendAnswer={wsMethods.sendAnswer}
      sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
    >
      <WorkflowScope workflowId={workflowId}>
        <ScopedCenterPanel activeBenchmark={activeBenchmark} />
      </WorkflowScope>
    </WSMethodProvider>
  );
}
