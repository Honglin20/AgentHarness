/**
 * P2-T9: Live status indicators driven by agent.api_retry + agent.status_update.
 *
 * - ApiRetryBadge: shows "retrying (2/3)" with the latest wait_seconds when
 *   the upstream LLM is silently retrying (rate limit / transient 5xx).
 *   Without this, users see "stuck" during the gap.
 * - StatusBadge: shows the latest claude-side liveness ("requesting" /
 *   "thinking" / etc.) during long gaps between message deltas.
 *
 * Formatting logic lives in ./executorErrorHelpers.ts (pure functions).
 */

import type { ApiRetryPayload, StatusUpdatePayload } from "@/types/events";
import {
  buildApiRetryBadgeText,
  buildStatusBadgeText,
} from "./executorErrorHelpers";

interface ApiRetryBadgeProps {
  payload: ApiRetryPayload;
}

export function ApiRetryBadge({ payload }: ApiRetryBadgeProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-1.5 inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400"
      data-testid="api-retry-badge"
    >
      <span className="animate-pulse">↻</span>
      <span>{buildApiRetryBadgeText(payload)}</span>
    </div>
  );
}

interface StatusBadgeProps {
  payload: StatusUpdatePayload;
}

export function StatusBadge({ payload }: StatusBadgeProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-1 inline-flex items-center gap-1 text-[10px] text-muted-foreground/70"
      data-testid="agent-status-badge"
      data-status={payload.status}
    >
      <span className="animate-pulse">·</span>
      <span className="font-mono">{buildStatusBadgeText(payload)}</span>
    </div>
  );
}
