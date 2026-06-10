/**
 * Agent streaming event handlers.
 */

import type { EventHandler } from "./types";
import { accumulateStepTokens } from "../workflowStores";
import type {
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentThinkingDeltaPayload,
  AgentToolOutputDeltaPayload,
  AgentToolOutputTruncatedPayload,
  BashBackgroundCompletedPayload,
  AgentRetryAttemptedPayload,
  AgentUsageUpdatePayload,
  AgentFailedWithClassifiedReasonPayload,
} from "@/types/events";
import { payload } from "./utils";
import { toast } from "sonner";

export const agentHandlers: [string, EventHandler][] = [
  [
    "agent.text_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentTextDeltaPayload>(event);
      stores.output.getState().appendText(p.node_id, p.text);
      stores.conversation.getState().appendAgentText(p.node_id, p.text);
    },
  ],

  [
    "agent.thinking_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentThinkingDeltaPayload>(event);
      stores.conversation.getState().appendAgentThinking(p.node_id, p.text);
    },
  ],

  [
    "agent.tool_call",
    (stores, event, ctx) => {
      const p = payload<AgentToolCallPayload>(event);
      const id = ctx.counter.next();
      stores.toolCall
        .getState()
        .addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      stores.conversation
        .getState()
        .addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
    },
  ],

  [
    "agent.tool_result",
    (stores, event, _ctx) => {
      const p = payload<AgentToolResultPayload>(event);
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find(
          (r) =>
            r.nodeId === p.node_id &&
            r.toolName === p.tool_name &&
            r.result === undefined
        );
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      stores.conversation
        .getState()
        .addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
    },
  ],

  [
    "agent.tool_output_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentToolOutputDeltaPayload>(event);
      stores.conversation
        .getState()
        .appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
    },
  ],

  [
    "agent.tool_output_truncated",
    (stores, event, _ctx) => {
      // Tool output exceeded MAX_OUTPUT_CHARS and was spilled to disk.
      // Surface as a system line in the conversation stream so the user can see
      // the bash output was compressed (the agent gets the file path via the
      // tool return value and can read_text_file it on demand).
      const p = payload<AgentToolOutputTruncatedPayload>(event);
      const note = `⚠️ ${p.tool_name} output truncated: ${p.total_chars.toLocaleString()} chars ` +
        `(> ${p.max_chars.toLocaleString()} max) — full output saved to ${p.output_path}`;
      stores.conversation
        .getState()
        .appendToolOutput(p.node_id, p.tool_name, note, "stdout");
    },
  ],

  [
    "bash.background_completed",
    (_stores, event, _ctx) => {
      // Background bash task finished (or timed out). Minimal handling for now —
      // log to console so it's visible during dev. A future PR can render a toast
      // or a status badge on the originating tool call.
      const p = payload<BashBackgroundCompletedPayload>(event);
      // eslint-disable-next-line no-console
      console.info(
        `[bash.background_completed] task=${p.task_id} exit=${p.exit_code} ` +
        `chars=${p.output_chars} truncated=${p.truncated} timed_out=${p.timed_out} ` +
        `monitor_error=${p.monitor_error ?? "none"}`,
      );
    },
  ],

  [
    "agent.retry_attempted",
    (stores, event, _ctx) => {
      // LLM call failed and will be retried. UI surfaces:
      //   - toast (immediate feedback)
      //   - inline retry status line on AgentMessage (persistent)
      // We do NOT clear partial text here — Pydantic AI's iter() will replay
      // from scratch and the new text stream will overwrite the old. (The
      // failed attempt's partial text is usually corrupted anyway.)
      //
      // Workflow filter: only act on the active workflow. If the user switched
      // away from a background workflow that's retrying, we don't pollute the
      // current view or toast-spam. The event is critical (never FIFO-evicted),
      // so when the user switches back, WS replay re-routes it through here
      // with the matching workflow_id.
      const p = payload<AgentRetryAttemptedPayload>(event);
      const currentWid = stores.workflow.getState().workflowId;
      if (currentWid && p.workflow_id !== currentWid) return;

      stores.workflow.getState().pushRetryAttempt(p.node_id, {
        attempt: p.attempt,
        maxAttempts: p.max_attempts,
        category: p.category,
        reason: p.reason,
        delayS: p.delay_s,
        retryAfterS: p.retry_after_s,
        ts: event.ts,
      });
      toast.warning(
        `Agent "${p.agent_name}" retrying (${p.attempt + 1}/${p.max_attempts}): ${p.category}`,
        { description: p.reason },
      );
    },
  ],

  [
    "agent.usage_update",
    (stores, event, _ctx) => {
      const p = payload<AgentUsageUpdatePayload>(event);
      const currentWid = stores.workflow.getState().workflowId;
      if (currentWid && p.workflow_id !== currentWid) return;

      // Per-step token attribution: compute delta from previous cumulative,
      // attribute to the active step (currentStepIdByNode).
      const prevUsage = stores.workflow.getState().nodes[p.node_id]?.tokenUsage;
      const newTotal = p.input_tokens + p.output_tokens;
      const prevTotal = prevUsage?.total ?? 0;

      if (newTotal > prevTotal) {
        const delta = {
          input: p.input_tokens - (prevUsage?.input ?? 0),
          output: p.output_tokens - (prevUsage?.output ?? 0),
          total: newTotal - prevTotal,
        };
        const activeStepId = stores.conversation.getState().currentStepIdByNode[p.node_id];
        if (activeStepId) {
          accumulateStepTokens(stores.todo, p.node_id, activeStepId, delta);
        }
      }

      stores.workflow.getState().setNodeUsage(
        p.node_id, p.requests, p.input_tokens, p.output_tokens,
      );
    },
  ],

  [
    "agent.failed_with_classified_reason",
    (stores, event, _ctx) => {
      // Final failure (retries exhausted OR classify said "don't retry").
      // Per user preference: NO toast — show inline error card on AgentMessage
      // so the failure reason stays visible (refresh-safe via critical event).
      // Workflow filter: same as the other two PR-D handlers.
      const p = payload<AgentFailedWithClassifiedReasonPayload>(event);
      const currentWid = stores.workflow.getState().workflowId;
      if (currentWid && p.workflow_id !== currentWid) return;
      stores.workflow.getState().setClassifiedFailure(p.node_id, {
        category: p.category,
        reason: p.reason,
        errorType: p.error_type,
        message: p.message,
        attemptsUsed: p.attempts_used,
        maxAttempts: p.max_attempts,
        ts: event.ts,
      });
    },
  ],
];
