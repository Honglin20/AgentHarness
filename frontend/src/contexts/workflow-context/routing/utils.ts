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

import { eventPayloadSchemas } from "@/types/eventSchemas";
import type { EventType } from "@/types/events";

/**
 * Validated payload extractor.
 * If a Zod schema exists for this event type, validates the payload.
 * On failure, logs a warning and falls back to the raw payload (graceful degradation).
 * Events without a schema pass through unvalidated.
 */
export function validatedPayload<T>(
  event: { type: string; payload: Record<string, unknown> },
): T {
  const schema = eventPayloadSchemas[event.type as EventType];
  if (!schema) return event.payload as unknown as T;

  const result = schema.safeParse(event.payload);
  if (result.success) return result.data as T;

  console.warn(
    `[EventValidation] "${event.type}" failed:`,
    result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
  );
  return event.payload as unknown as T;
}

/** Typed payload extractor — routes through validation. */
export function payload<T>(event: { type: string; payload: Record<string, unknown> }): T {
  return validatedPayload<T>(event);
}

// ---------------------------------------------------------------------------
// resetAllStores
// ---------------------------------------------------------------------------

/** Reset all stores in a WorkflowStores container.

 * Every store in WorkflowStores MUST be listed here — anything missing
 * survives workflow switches and surfaces as cross-workflow data leak
 * (the previous workflow's content appears in the new workflow's UI).
 */
export function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.span.getState().reset();
  stores.todo.getState().reset();
}

// ---------------------------------------------------------------------------
// Re-export dedup utilities
// ---------------------------------------------------------------------------

export { _processedSeqsByWorkflow, cleanupSeqTracker } from "./dedup";
