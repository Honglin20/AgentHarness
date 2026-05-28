/**
 * WorkflowCenterPanel - Context architecture + stable WebSocket management.
 *
 * WebSocket lives here (stable parent that never remounts on workflow switch).
 * Events are routed via eventRouter to scoped stores inside WorkflowScope.
 *
 * Decisions made HERE:
 * - replay mode → ScopedCenterPanel (read-only, no WS needed)
 * - no workflowId → legacy CenterPanel (landing page, no WorkflowScope needed)
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
import { ConnectionStatusBar } from "./ConnectionStatusBar";

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Replay mode: use the replay run's ID (stores already populated by viewStore)
  if (activeView.type === "replay") {
    return activeView.runId;
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
  const isReplay = activeView.type === "replay";

  // WebSocket managed at this stable level — survives workflow switches
  // No WS needed for replay mode (stores already populated by viewStore)
  const wsMethods = useWorkflowWS(isReplay ? null : workflowId);

  // No workflowId (landing page / no active run): use legacy CenterPanel
  // WorkflowScope cannot render without a workflowId (SSR: getWorkflowManager needs window)
  if (!workflowId) {
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  return (
    <WorkflowScope workflowId={workflowId}>
      {!isReplay && <ConnectionStatusBar isConnected={wsMethods.isConnected} />}
      <WSMethodProvider
        sendAnswer={wsMethods.sendAnswer}
        sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
      >
        <ScopedCenterPanel activeBenchmark={activeBenchmark} isReplay={isReplay} />
      </WSMethodProvider>
    </WorkflowScope>
  );
}
