/**
 * WorkflowScope — pure DI container for per-workflow scoped stores.
 *
 * WS lifecycle lives in WorkflowCenterPanel (stable parent).
 * WorkflowScope just provides the scoped stores via WorkflowProvider.
 * WSMethodContext is a real React context — no window globals.
 *
 * Reset responsibility has been moved out of this component (see fix plan
 * 2026-05-30): reset now happens at data write entries:
 *   - live: routeEvent on `workflow.started` (with idempotent guard)
 *   - replay: replayEventsToStores entry calls resetAllStores
 * This eliminates the Bug A: refresh-then-history blank-panel regression
 * (the previous reset effect wiped data that replayEventsToStores had just
 * populated, before React handed control back to the renderer).
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
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
  sendFollowup: (agentName: string, question: string) => void;
}

const WSMethodContext = createContext<WSMethods | null>(null);

export function WSMethodProvider({
  sendAnswer,
  sendStructuredAnswer,
  sendStopAndRegenerate,
  sendGuidance,
  sendFollowup,
  children,
}: WSMethods & { children: ReactNode }) {
  const value = useMemo(
    () => ({ sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup }),
    [sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup],
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
    // Tell the manager which workflow is active for cross-cutting reads.
    // Reset responsibility lives at data write entries (see file header).
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
