/**
 * DTO → UI message conversion for the conversation store.
 *
 * Server JSON (the `conversation` array on `RunRecord`) is untyped at the
 * wire boundary. `ConversationMessageDTO` is the structural shape we expect;
 * `dtoListToMessages` converts to the richly-typed `ConversationMessage`
 * the UI store uses, filling in safe defaults for any missing fields.
 *
 * Why a dedicated converter (instead of `as ConversationMessage`)?
 *   - Defaults become explicit and testable.
 *   - Schema drift on the server surfaces here, not in random UI render code.
 *   - Both replay paths (loadRunFromPersistedData + loadLegacyRunData) share
 *     the same mapping instead of duplicating it inline.
 */

import type { ConversationMessage } from "@/stores/conversationStore";

/**
 * Wire format for a single persisted conversation message.
 *
 * Every field is optional except `type` — the server guarantees a type
 * discriminator, but legacy / partial data may omit anything else. The
 * converter applies defaults per field.
 */
export interface ConversationMessageDTO {
  /** Optional — server-side id; fallback applied by converter if missing. */
  id?: string;
  /** Required discriminator. */
  type: "agent" | "user" | "tool_call" | "system" | "question";
  nodeId?: string;
  /** Defaults to empty string when missing. */
  content?: string;
  agentName?: string;
  thinking?: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  /** Defaults to "done" — persisted tool calls always finished. */
  toolStatus?: "running" | "done";
  toolDurationMs?: number;
  toolStreamingOutput?: string;
  /** Status string from server; unknown values fall back to "done". */
  status?: string;
  durationMs?: number;
  /** Defaults to 0 when missing (legacy data). */
  timestamp?: number;
  /**
   * 1-indexed loop iteration that produced this message. Undefined for
   * legacy data (frontend treats as iter=1) and for non-cycle messages.
   * Backend writes this from `builder.node_invocation_counts` (live) or
   * `iter_index` (snapshot save). Per-iter sidecar responses stamp it
   * from the requested iter_num.
   */
  iteration?: number;
  // ── question-specific (only meaningful when type === "question") ──
  questionId?: string;
  questionHeader?: string | null;
  questionOptions?: Array<{ label: string; description?: string | null; value?: string | null }> | null;
  questionMultiSelect?: boolean;
  questionAllowCustomInput?: boolean;
  questionInputType?: "text" | "number" | "url" | "textarea";
  questionInputPlaceholder?: string | null;
  questionAnswer?: { selected: string[]; customInput: string };
  // ── follow-up marker ──
  followup?: boolean;
}

const KNOWN_UI_STATUSES = new Set<ConversationMessage["status"]>([
  "streaming",
  "done",
  "error",
  "interrupted",
  "pending",
  "answered",
  "timeout",
]);

function coerceStatus(raw: string | undefined): ConversationMessage["status"] {
  if (raw && (KNOWN_UI_STATUSES as Set<string>).has(raw)) {
    return raw as ConversationMessage["status"];
  }
  return "done";
}

/**
 * Convert a single DTO to a UI message.
 *
 * @param dto           Wire-format message from server.
 * @param fallbackIndex Used to synthesize an id if `dto.id` is missing.
 *                      Callers should pass the array index so synthetic ids
 *                      are stable across renders for the same input.
 */
export function dtoToMessage(dto: ConversationMessageDTO, fallbackIndex: number): ConversationMessage {
  return {
    id: dto.id ?? `replay-${fallbackIndex}`,
    type: dto.type,
    nodeId: dto.nodeId,
    content: dto.content ?? "",
    agentName: dto.agentName,
    thinking: dto.thinking,
    toolName: dto.toolName,
    toolArgs: dto.toolArgs,
    toolResult: dto.toolResult,
    // Persisted tool calls have always finished (the server only writes the
    // conversation record after the tool returns). Default to "done" so the
    // UI's "running" indicator never appears on replayed messages.
    toolStatus: dto.toolStatus ?? "done",
    toolDurationMs: dto.toolDurationMs,
    toolStreamingOutput: dto.toolStreamingOutput,
    status: coerceStatus(dto.status),
    durationMs: dto.durationMs,
    timestamp: dto.timestamp ?? 0,
    iteration: dto.iteration,
    questionId: dto.questionId,
    questionHeader: dto.questionHeader,
    questionOptions: dto.questionOptions,
    questionMultiSelect: dto.questionMultiSelect,
    questionAllowCustomInput: dto.questionAllowCustomInput,
    questionInputType: dto.questionInputType,
    questionInputPlaceholder: dto.questionInputPlaceholder,
    questionAnswer: dto.questionAnswer,
    followup: dto.followup,
  };
}

/** Convert a list of DTOs. Empty input → empty output (no synthetic entries). */
export function dtoListToMessages(dtos: ConversationMessageDTO[]): ConversationMessage[] {
  return dtos.map((dto, i) => dtoToMessage(dto, i));
}
