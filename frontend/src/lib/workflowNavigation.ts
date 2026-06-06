/**
 * Workflow Navigation — lightweight bridge for low-level modules that need
 * setActiveWorkflowId without pulling in the entire workflow-context barrel.
 *
 * Dependency: only WorkflowManager (no stores, no React context).
 */

import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";

export function setActiveWorkflowId(id: string | null): void {
  getWorkflowManager().setActiveWorkflowId(id);
}
