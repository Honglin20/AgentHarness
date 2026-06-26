/**
 * P2-T9: Pure formatting helpers for the executor error / retry / status UI.
 *
 * Extracted from the .tsx components so vitest can test them without
 * hitting the JSX transform limitation in this repo (vitest 4 + oxc
 * parser inherits tsconfig's jsx:"preserve"). Component render is
 * trusted (prop-driven display only — no logic in JSX).
 */

import type {
  ExecutorErrorPayload,
  ApiRetryPayload,
  StatusUpdatePayload,
} from "@/types/events";

export function buildExecutorErrorHeadline(p: ExecutorErrorPayload): string {
  const phaseTag = p.phase ? `[${p.phase}]` : "";
  const timedOutTag = p.timed_out ? " (timed out)" : "";
  const exitTag =
    p.exit_code !== undefined && p.exit_code !== null
      ? ` (exit ${p.exit_code})`
      : "";
  // Collapse extra spaces when phase is empty
  const head = `${p.executor} ${phaseTag} failure: ${p.error_type}${timedOutTag}${exitTag}`;
  return head.replace(/\s+/g, " ").trim();
}

export function shouldShowRetryAttempt(p: ExecutorErrorPayload): boolean {
  return p.retry_attempt !== undefined && p.retry_attempt > 0;
}

export function shouldShowStderrTail(p: ExecutorErrorPayload): boolean {
  return Boolean(p.stderr_tail && p.stderr_tail.trim().length > 0);
}

export function buildApiRetryBadgeText(p: ApiRetryPayload): string {
  const counter =
    p.retry_count !== undefined && p.max_retries !== undefined
      ? `${p.retry_count}/${p.max_retries}`
      : p.retry_count !== undefined
        ? `#${p.retry_count}`
        : "";
  const wait =
    p.wait_seconds !== undefined ? ` · waiting ${p.wait_seconds.toFixed(1)}s` : "";
  const err = p.error_message ? ` · ${p.error_message}` : "";
  return `Retrying${counter ? ` (${counter})` : ""}${wait}${err}`;
}

export function buildStatusBadgeText(p: StatusUpdatePayload): string {
  const dur = p.duration_ms !== undefined ? ` · ${p.duration_ms}ms` : "";
  return `${p.status}${dur}`;
}
