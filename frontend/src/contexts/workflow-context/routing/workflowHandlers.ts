/**
 * Workflow lifecycle event handlers.
 */

import type { EventHandler } from "./types";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
} from "@/types/events";
import { computeRunSummary } from "@/lib/summary/runSummary";
import { payload, resetAllStores, formatOutputAsMd } from "./utils";
import { _processedSeqsByWorkflow, cleanupSeqTracker } from "./dedup";

export const workflowHandlers: [string, EventHandler][] = [
  [
    "workflow.started",
    (stores, event, _ctx) => {
      const p = payload<WorkflowStartedPayload>(event);
      // Idempotent reset: only reset if this is a different workflow or empty state.
      // Prevents WS reconnect (since_seq=0 re-pushes workflow.started) from wiping data.
      const currentWid = stores.workflow.getState().workflowId;
      const nodesCount = Object.keys(stores.workflow.getState().nodes).length;
      const sameWorkflow = currentWid === p.workflow_id && nodesCount > 0;
      if (!sameWorkflow) {
        resetAllStores(stores);
        // Clear the OLD workflow's seq tracker (currentWid), not the new one
        if (currentWid) _processedSeqsByWorkflow.delete(currentWid);
      }
      stores.span.getState().setWorkflowStartTs(p.started_ts_ms ?? event.ts);
      stores.workflow.getState().setActiveWorkflowId(p.workflow_id);
      stores.workflow.getState().handleWorkflowStarted(p);
    },
  ],

  [
    "workflow.completed",
    (stores, event, ctx) => {
      const p = payload<WorkflowCompletedPayload>(event);
      stores.workflow.getState().handleWorkflowCompleted(p);
      const summaryNodes = Object.values(stores.workflow.getState().nodes);
      const addChart = stores.chart.getState().addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      cleanupSeqTracker(p.workflow_id);
    },
  ],

  [
    "workflow.error",
    (stores, event, ctx) => {
      const p = payload<{ workflow_id: string; error: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "failed",
      });
      stores.output.getState().setWorkflowError(p.error);
      const summaryNodes = Object.values(stores.workflow.getState().nodes);
      const addChart = stores.chart.getState().addChart;
      computeRunSummary(summaryNodes, addChart, stores.span);
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      cleanupSeqTracker(p.workflow_id);
    },
  ],

  [
    "workflow.cancelled",
    (stores, event, ctx) => {
      const p = payload<{ workflow_id: string }>(event);
      stores.workflow.getState().handleWorkflowCompleted({
        workflow_id: p.workflow_id,
        status: "paused",
      });
      if (ctx.persistence) {
        ctx.persistence.saveConversation(p.workflow_id);
        ctx.persistence.saveCharts(p.workflow_id);
      }
      cleanupSeqTracker(p.workflow_id);
    },
  ],

  [
    "workflow.interrupted",
    (_stores, _event, _ctx) => {
      // No longer used — kept for backward compat
    },
  ],

  [
    "workflow.waiting_for_guidance",
    (_stores, _event, _ctx) => {
      // UI is already in awaitingGuidance state from handleStop
    },
  ],

  [
    "workflow.resumed",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; node_id: string; directive?: string }>(event);
      stores.conversation.getState().resumeAgentMessage(p.node_id, "");
    },
  ],
];
