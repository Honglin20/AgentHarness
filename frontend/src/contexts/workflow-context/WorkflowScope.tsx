/**
 * WorkflowScope - Context Provider wrapper
 *
 * WS lifecycle lives in WorkflowCenterPanel (stable parent).
 * WorkflowScope just provides per-workflow scoped stores via WorkflowProvider.
 * WSMethodContext is a real React context — no window globals.
 */

"use client";

import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";

// ============================================================
// WSMethodContext — React context for WebSocket send methods
// ============================================================

interface WSMethods {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

const WSMethodContext = createContext<WSMethods | null>(null);

export function WSMethodProvider({
  sendAnswer,
  sendStopAndRegenerate,
  children,
}: WSMethods & { children: ReactNode }) {
  const value = useMemo(
    () => ({ sendAnswer, sendStopAndRegenerate }),
    [sendAnswer, sendStopAndRegenerate],
  );
  return (
    <WSMethodContext.Provider value={value}>
      {children}
    </WSMethodContext.Provider>
  );
}

export function useWSMethods(): WSMethods {
  const ctx = useContext(WSMethodContext);
  if (!ctx) {
    throw new Error(
      "useWSMethods must be used within WSMethodProvider. " +
      "Make sure WorkflowCenterPanel wraps the tree with WSMethodProvider."
    );
  }
  return ctx;
}

// ============================================================
// WorkflowScope
// ============================================================

interface WorkflowScopeProps {
  workflowId: string | null;
  children: ReactNode;
}

export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  if (!stores) return <>{children}</>;

  return (
    <WorkflowProvider
      workflowId={workflowId}
      stores={stores}
      setActiveWorkflowId={setActiveWorkflowId}
    >
      {children}
    </WorkflowProvider>
  );
}
