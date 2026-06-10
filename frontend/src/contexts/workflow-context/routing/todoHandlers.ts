/**
 * TODO step event handlers.
 */

import type { EventHandler } from "./types";
import type {
  TodoCreatedPayload,
  TodoUpdatedPayload,
  TodoBulkCompletedPayload,
  TodoReplacedPayload,
} from "@/types/events";
import {
  handleTodoCreated,
  handleTodoUpdated,
  handleTodoBulkCompleted,
  handleTodoReplaced,
} from "../workflowStores";
import { payload } from "./utils";

export const todoHandlers: [string, EventHandler][] = [
  [
    "todo.created",
    (stores, event, _ctx) => {
      const p = payload<TodoCreatedPayload>(event);
      handleTodoCreated(stores.todo, p.node_id, p.items);
      // First step is auto-in_progress on the server side; sync the
      // currentStepIdByNode so trailing agent.tool_call / text_delta events
      // get stamped with the active step id.
      const firstInProgress = p.items.find((it) => it.status === "in_progress");
      if (firstInProgress) {
        stores.conversation.getState().setCurrentStep(p.node_id, firstInProgress.task_id);
      }
    },
  ],

  [
    "todo.updated",
    (stores, event, _ctx) => {
      const p = payload<TodoUpdatedPayload>(event);
      handleTodoUpdated(
        stores.todo,
        p.node_id,
        p.task_id,
        (p.status ?? undefined) as
          | ("in_progress" | "completed" | "skipped")
          | undefined,
        p.detail,
        p.auto_advance,
      );

      // Sync currentStepIdByNode so subsequent agent.tool_call / text_delta
      // events get stamped with the active step's id (used by the
      // conversation UI to group details under StepRows).
      //
      // Two paths can set a new active step:
      //   1. status=in_progress on this event
      //   2. auto_advance.next_task_id (server auto-advances when the agent
      //      asked for it in one todo call)
      //
      // R9 fix: when a step becomes terminal (completed/skipped) AND there
      // is no auto_advance to a new in_progress step, clear the current
      // step pointer for this node — there is no "active" step anymore.
      const conv = stores.conversation.getState();
      if (p.status === "in_progress") {
        conv.setCurrentStep(p.node_id, p.task_id);
      } else if (p.auto_advance?.status === "in_progress" && p.auto_advance.next_task_id) {
        conv.setCurrentStep(p.node_id, p.auto_advance.next_task_id);
      } else if (p.status === "completed" || p.status === "skipped") {
        // Step went terminal without auto-advance: this was the last active
        // step. Clear the pointer so trailing agent output isn't falsely
        // attributed to it.
        conv.setCurrentStep(p.node_id, null);
      }
    },
  ],

  [
    "todo.bulk_completed",
    (stores, event, _ctx) => {
      const p = payload<TodoBulkCompletedPayload>(event);
      handleTodoBulkCompleted(
        stores.todo,
        p.node_id,
        p.status,
        p.task_ids,
        p.reason,
      );
      // All steps terminal — no current step anymore.
      stores.conversation.getState().setCurrentStep(p.node_id, null);
    },
  ],

  [
    "todo.replaced",
    (stores, event, _ctx) => {
      const p = payload<TodoReplacedPayload>(event);
      handleTodoReplaced(stores.todo, p.node_id, p.items);
      // New plan: point currentStep at the first in_progress step (server
      // sets step[0] to in_progress on replace, mirroring create).
      const firstInProgress = p.items.find((it) => it.status === "in_progress");
      stores.conversation.getState().setCurrentStep(
        p.node_id,
        firstInProgress ? firstInProgress.task_id : null,
      );
    },
  ],
];
