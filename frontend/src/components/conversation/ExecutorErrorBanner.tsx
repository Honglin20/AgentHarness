/**
 * P2-T9: Inline banner rendering for structured executor failures.
 *
 * Surfaces the agent.executor_error payload (P2-T1/T3) — phase / stderr_tail
 * / exit_code / retry_attempt / executor — so users see WHY an agent failed
 * without digging into logs. Distinct from the classifiedFailure banner:
 * that one shows retry-budget exhaustion; this one shows the per-attempt
 * structured failure that the executor emitted.
 *
 * Render logic lives in ./executorErrorHelpers.ts (pure functions) — tested
 * directly. JSX below is prop-driven display only.
 */

import type { ExecutorErrorPayload } from "@/types/events";
import {
  buildExecutorErrorHeadline,
  shouldShowRetryAttempt,
  shouldShowStderrTail,
} from "./executorErrorHelpers";

interface Props {
  payload: ExecutorErrorPayload;
}

export function ExecutorErrorBanner({ payload }: Props) {
  const { error_message, stderr_tail, retry_attempt } = payload;
  const headline = buildExecutorErrorHeadline(payload);

  return (
    <div
      role="alert"
      aria-live="polite"
      className="mt-2 rounded-md border border-red-500/40 bg-red-500/5 px-3 py-2 text-[11px]"
      data-testid="executor-error-banner"
      data-phase={payload.phase}
      data-executor={payload.executor}
    >
      <div className="flex items-center gap-1.5 text-red-600 dark:text-red-400">
        <span>⚠️</span>
        <span className="font-medium" data-testid="executor-error-headline">
          {headline}
        </span>
      </div>
      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/80">
        {error_message}
      </p>
      {shouldShowStderrTail(payload) && (
        <pre
          data-testid="executor-error-stderr"
          className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-background/60 p-1.5 font-mono text-[10px] text-muted-foreground"
        >
          {stderr_tail}
        </pre>
      )}
      {shouldShowRetryAttempt(payload) && (
        <p className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">
          attempt #{retry_attempt}
        </p>
      )}
    </div>
  );
}
