/**
 * Shared utilities for event routing handlers.
 */

import type { WSEvent } from "@/types/events";
import type { WorkflowStores } from "../workflowStores";
import { _processedSeqsByWorkflow } from "./dedup";

// ---------------------------------------------------------------------------
// formatOutputAsMd
// ---------------------------------------------------------------------------

/** More complete version (from replayEvents.ts) — handles summary/details/table. */
export function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") {
    try {
      const parsed = JSON.parse(output);
      return formatOutputAsMd(parsed);
    } catch {
      return output;
    }
  }

  if (typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    const lines: string[] = [];
    if (obj.summary) lines.push(String(obj.summary));
    if (obj.details) lines.push("", String(obj.details));

    const extra = Object.entries(obj).filter(
      ([k]) => k !== "summary" && k !== "details"
    );
    if (extra.length > 0) {
      lines.push("", "| Field | Value |", "|-------|-------|");
      for (const [k, v] of extra) {
        const val = typeof v === "object" ? JSON.stringify(v) : String(v);
        lines.push(`| ${k} | ${val} |`);
      }
    }
    if (lines.length > 0) return lines.join("\n");
  }

  return JSON.stringify(output, null, 2);
}

// ---------------------------------------------------------------------------
// payload helper
// ---------------------------------------------------------------------------

/** Typed payload extractor. */
export function payload<T>(event: WSEvent): T {
  return event.payload as unknown as T;
}

// ---------------------------------------------------------------------------
// resetAllStores
// ---------------------------------------------------------------------------

/** Reset all stores in a WorkflowStores container. */
export function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
  stores.span.getState().reset();
}

// ---------------------------------------------------------------------------
// Re-export dedup utilities
// ---------------------------------------------------------------------------

export { _processedSeqsByWorkflow, cleanupSeqTracker } from "./dedup";
