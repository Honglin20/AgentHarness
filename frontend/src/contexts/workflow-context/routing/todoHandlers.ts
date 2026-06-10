/**
 * TODO step event handlers.
 */

import type { EventHandler } from "./types";
import type { TodoCreatedPayload, TodoUpdatedPayload } from "@/types/events";
import { handleTodoCreated, handleTodoUpdated } from "../workflowStores";
import { payload } from "./utils";

export const todoHandlers: [string, EventHandler][] = [
  [
    "todo.created",
    (stores, event, _ctx) => {
      const p = payload<TodoCreatedPayload>(event);
      handleTodoCreated(stores.todo, p.node_id, p.items);
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
        p.status ?? undefined,
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
      // We deliberately do NOT clear on status=completed — trailing agent
      // output after the last step still belongs to that step.
      const conv = stores.conversation.getState();
      if (p.status === "in_progress") {
        conv.setCurrentStep(p.node_id, p.task_id);
      } else if (p.auto_advance?.status === "in_progress" && p.auto_advance.next_task_id) {
        conv.setCurrentStep(p.node_id, p.auto_advance.next_task_id);
      }
    },
  ],
];
