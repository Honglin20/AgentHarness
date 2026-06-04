/**
 * WorkflowCenterPanel - Context architecture + stable WebSocket management.
 *
 * WebSocket lives here (stable parent that never remounts on workflow switch).
 * Events are routed via eventRouter to scoped stores.
 * WorkflowScope is provided by page.tsx (wraps both center and diagnostics panels).
 *
 * Decisions made HERE:
 * - replay mode → ScopedCenterPanel (read-only, no WS needed)
 * - no workflowId → legacy CenterPanel (landing page)
 * - valid workflowId → Context architecture (WSMethodContext)
 */

"use client";

import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
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

  if (activeView.type === "replay") {
    return activeView.runId;
  }

  if (activeBatchId) {
    return selectedRunId;
  }

  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);
  const isReplay = activeView.type === "replay";

  // WebSocket managed at this stable level — survives workflow switches
  const wsMethods = useWorkflowWS(isReplay ? null : workflowId);

  // No workflowId (landing page / no active run): use legacy CenterPanel
  if (!workflowId) {
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  // WorkflowScope is provided by page.tsx — no inner scope needed here.
  return (
    <>
      {!isReplay && <ConnectionStatusBar isConnected={wsMethods.isConnected} />}
      <WSMethodProvider
        sendAnswer={wsMethods.sendAnswer}
        sendStructuredAnswer={wsMethods.sendStructuredAnswer}
        sendStopAndRegenerate={wsMethods.sendStopAndRegenerate}
        sendGuidance={wsMethods.sendGuidance}
        sendFollowup={wsMethods.sendFollowup}
      >
        <ScopedCenterPanel activeBenchmark={activeBenchmark} isReplay={isReplay} />
      </WSMethodProvider>
    </>
  );
}
