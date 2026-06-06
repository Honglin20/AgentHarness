/**
 * Shared types for the event routing handler registry.
 */

import type { WSEvent } from "@/types/events";
import type { WorkflowStores } from "../workflowStores";
import { getToolCallCounter } from "../workflowStores";

// ---------------------------------------------------------------------------
// RouteContext
// ---------------------------------------------------------------------------

export type RouteMode = "live" | "replay";

export interface RoutePersistence {
  saveConversation: (wid: string) => Promise<void>;
  saveCharts: (wid: string) => Promise<void>;
}

export interface RouteContext {
  mode: RouteMode;
  persistence: RoutePersistence | null;
  counter: ReturnType<typeof getToolCallCounter>;
}

// ---------------------------------------------------------------------------
// Handler / Registry types
// ---------------------------------------------------------------------------

export type EventHandler = (
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
) => void;

export type EventRegistry = Map<string, EventHandler>;
