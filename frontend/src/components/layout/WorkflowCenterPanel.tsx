/**
 * WorkflowCenterPanel - Context architecture + stable WebSocket management.
 *
 * WebSocket lives here (stable parent that never remounts on workflow switch).
 * Events are routed via eventRouter to scoped stores.
 * WorkflowScope is provided by page.tsx (wraps both center and diagnostics panels).
 *
 * No legacy CenterPanel fallback — ScopedCenterPanel handles all states.
 * ScopedCenterPanel is loaded with ssr: false because it uses workflow-scoped
 * context hooks that require a Provider (absent during SSG prerendering).
 */

"use client";

import dynamic from "next/dynamic";
import { useViewStore, isReplayView, getActiveRunId } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WSMethodProvider } from "@/contexts/workflow-context/WorkflowScope";
import { useWorkflowWS } from "@/contexts/workflow-context/useWorkflowWS";
import { ConnectionStatusBar } from "./ConnectionStatusBar";

// Load ScopedCenterPanel client-only to avoid SSG prerender errors
// (scoped context hooks require WorkflowProvider, absent during static export)
const ScopedCenterPanel = dynamic(
  () => import("./ScopedCenterPanel").then((m) => m.ScopedCenterPanel),
  { ssr: false },
);

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  if (isReplayView(activeView)) {
    return getActiveRunId(activeView);
  }

  if (activeBatchId) {
    return selectedRunId;
  }

  return workflowId;
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);
  const isReplay = isReplayView(activeView);

  // WebSocket managed at this stable level — survives workflow switches.
  // Replay mode skips WS connection (read-only).
  const wsMethods = useWorkflowWS(isReplay ? null : workflowId);

  return (
    <>
      {workflowId && !isReplay && (
        <ConnectionStatusBar isConnected={wsMethods.isConnected} />
      )}
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
