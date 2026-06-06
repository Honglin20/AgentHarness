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
    },
  ],
];
