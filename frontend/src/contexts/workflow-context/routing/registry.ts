/**
 * Event handler registry — builds the Map from all handler modules.
 */

import type { EventRegistry } from "./types";
import { workflowHandlers } from "./workflowHandlers";
import { nodeHandlers } from "./nodeHandlers";
import { agentHandlers } from "./agentHandlers";
import { chatHandlers } from "./chatHandlers";
import { chartHandlers } from "./chartHandlers";
import { todoHandlers } from "./todoHandlers";
import { spanHandlers } from "./spanHandlers";

export const eventRegistry: EventRegistry = new Map([
  ...workflowHandlers,
  ...nodeHandlers,
  ...agentHandlers,
  ...chatHandlers,
  ...chartHandlers,
  ...todoHandlers,
  ...spanHandlers,
]);
