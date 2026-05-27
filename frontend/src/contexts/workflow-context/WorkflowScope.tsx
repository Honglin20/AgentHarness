/**
 * WorkflowScope - Context Provider wrapper
 *
 * Phase 2 updated: WS lifecycle moved to WorkflowCenterPanel.
 * WorkflowScopeInner no longer creates WebSocket connections.
 */

"use client";

import { useEffect, useMemo, type ReactNode } from "react";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";
import { useScopedWorkflowEvents } from "./useWorkflowEvents";

interface WorkflowScopeProps {
  workflowId: string | null;
  batchId?: string | null;
  children: ReactNode;
}

export function WorkflowScope({ workflowId, batchId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);

  const { selectedRunId } = useBatchStore();

  // In batch mode, use selectedRunId as the workflowId
  const effectiveWorkflowId = batchId ? selectedRunId : workflowId;

  const stores = useMemo(() => {
    if (!effectiveWorkflowId) return null;
    return manager.getOrCreate(effectiveWorkflowId).stores;
  }, [manager, effectiveWorkflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    manager.setActiveWorkflowId(effectiveWorkflowId);
  }, [manager, effectiveWorkflowId]);

  if (!stores) return <>{children}</>;

  return (
    <WorkflowProvider
      workflowId={effectiveWorkflowId}
      stores={stores}
      setActiveWorkflowId={setActiveWorkflowId}
    >
      <WorkflowScopeInner>
        {children}
      </WorkflowScopeInner>
    </WorkflowProvider>
  );
}

/**
 * Inner component rendered inside WorkflowProvider so it can access context.
 * Sets the __useContextArchitecture flag and provides WS methods to child tree.
 */
function WorkflowScopeInner({ children }: { children: ReactNode }) {
  const { sendAnswer, sendStopAndRegenerate } = useScopedWorkflowEvents();

  // Mark that we're in Context architecture mode
  useEffect(() => {
    (window as unknown as { __useContextArchitecture?: boolean }).__useContextArchitecture = true;
    return () => {
      delete (window as unknown as { __useContextArchitecture?: boolean }).__useContextArchitecture;
    };
  }, []);

  return (
    <WSMethodProvider
      sendAnswer={sendAnswer}
      sendStopAndRegenerate={sendStopAndRegenerate}
    >
      {children}
    </WSMethodProvider>
  );
}

export function WSMethodProvider({
  sendAnswer,
  sendStopAndRegenerate,
  children,
}: {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const wsMethods = { sendAnswer, sendStopAndRegenerate };
    (window as unknown as { __wsMethods?: typeof wsMethods }).__wsMethods = wsMethods;
    return () => {
      delete (window as unknown as { __wsMethods?: typeof wsMethods }).__wsMethods;
    };
  }, [sendAnswer, sendStopAndRegenerate]);

  return <>{children}</>;
}

export function getWSMethods() {
  return (window as unknown as { __wsMethods?: {
    sendAnswer?: (questionId: string, answer: string) => void;
    sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  } }).__wsMethods ?? {};
}
