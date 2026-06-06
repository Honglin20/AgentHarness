/**
 * Public API for the event routing handler registry.
 */

import type { WSEvent } from "@/types/events";
import type { WorkflowStores } from "../workflowStores";
import type { RouteContext, RouteMode, RoutePersistence } from "./types";
import { eventRegistry } from "./registry";
import { isDuplicate } from "./dedup";

// Re-export types
export type { RouteContext, RouteMode, RoutePersistence };
export type { EventHandler, EventRegistry } from "./types";

// Re-export utilities
export { cleanupSeqTracker, _processedSeqsByWorkflow } from "./dedup";
export { resetAllStores, formatOutputAsMd, payload } from "./utils";

// ---------------------------------------------------------------------------
// routeEvent — registry-based implementation
// ---------------------------------------------------------------------------

/**
 * Shared Event Router — single source of truth for live + replay event routing.
 *
 * - live mode (ctx.persistence !== null): triggers API persistence side effects
 * - replay mode (ctx.persistence === null): skips API calls
 * - workflow.started includes idempotent reset (replaces WorkflowScope reset effect)
 */
export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void {
  // 1. Dedup middleware
  const wid = stores.workflow.getState().workflowId ?? undefined;
  if (isDuplicate(wid, event.seq)) return;

  // 2. Registry lookup
  const handler = eventRegistry.get(event.type);
  if (handler) {
    handler(stores, event, ctx);
  }
  // default: silently ignore unknown event types
}
