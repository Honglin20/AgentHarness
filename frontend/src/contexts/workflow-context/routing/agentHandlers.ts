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
  ExecutorErrorPayload,
  ApiRetryPayload,
  StatusUpdatePayload,
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
      const toolCallId = p.tool_call_id;
      stores.toolCall
        .getState()
        .addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {}, toolCallId);
      stores.conversation
        .getState()
        .addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {}, toolCallId);
    },
  ],

  [
    "agent.tool_result",
    (stores, event, _ctx) => {
      const p = payload<AgentToolResultPayload>(event);
      const toolCallId = p.tool_call_id;
      // toolCall store: translate tool_call_id → record.id (the client-side
      // tc-N key). Conversation store matches by toolCallId directly.
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .find((r) => r.toolCallId === toolCallId && r.result === undefined);
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      stores.conversation
        .getState()
        .addToolResult(toolCallId, String(p.result ?? ""));
    },
  ],

  [
    "agent.tool_output_delta",
    (stores, event, _ctx) => {
      // NOTE: tool_output_delta does not yet carry tool_call_id (see G.3 in
      // the fix plan). Matching falls back to the last running call of the
      // same (nodeId, toolName) — fine for sequential bash, can cross-wire
      // for parallel same-name bash streaming (rare; tracked as follow-up).
      const p = payload<AgentToolOutputDeltaPayload>(event);
      // Find the last running tool_call on this node with the same name and
      // route the streaming line to it. Future: extend WS payload + schema
      // to carry tool_call_id here too.
      const convState = stores.conversation.getState();
      const messages = convState.messages;
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (
          m.type === "tool_call" &&
          m.nodeId === p.node_id &&
          m.toolName === p.tool_name &&
          m.toolResult === undefined &&
          m.toolCallId
        ) {
          convState.appendToolOutput(m.toolCallId, p.line, p.stream);
          return;
        }
      }
      // No matching running call — drop the line (better than landing on a
      // completed/unrelated message).
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
      // Same fallback strategy as tool_output_delta above.
      const convState = stores.conversation.getState();
      const messages = convState.messages;
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (
          m.type === "tool_call" &&
          m.nodeId === p.node_id &&
          m.toolName === p.tool_name &&
          m.toolResult === undefined &&
          m.toolCallId
        ) {
          convState.appendToolOutput(m.toolCallId, note, "stdout");
          return;
        }
      }
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
      const newTotal = p.total_tokens;
      const prevTotal = prevUsage?.total ?? 0;

      if (newTotal > prevTotal) {
        const delta = {
          input: Math.max(0, p.input_tokens - (prevUsage?.input ?? 0)),
          output: Math.max(0, p.output_tokens - (prevUsage?.output ?? 0)),
          total: newTotal - prevTotal,
        };
        const activeStepId = stores.conversation.getState().currentStepIdByNode[p.node_id];
        if (activeStepId) {
          accumulateStepTokens(stores.todo, p.node_id, activeStepId, delta);
        }
      }

      stores.workflow.getState().setNodeUsage(
        p.node_id,
        p.requests,
        p.input_tokens,
        p.output_tokens,
        // Stage-2 fields — undefined on old events. BudgetBar hides the
        // Window bar when last_* is missing rather than misleading users.
        p.last_input,
        p.last_output,
        p.cumulative_cache_hit ?? p.cache_hit,
        p.last_cache_hit,
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

  [
    "agent.executor_error",
    (stores, event, _ctx) => {
      // P2-T1/T3: structured executor failure (stderr_tail / phase /
      // exit_code / retry_attempt). Stash on the node so toast / banner
      // can render the WHY. Toast fires here for immediate feedback;
      // node.failed (from node_factory except) still owns lifecycle.
      const p = payload<ExecutorErrorPayload>(event);
      const currentWid = stores.workflow.getState().workflowId;
      if (currentWid && p.workflow_id !== currentWid) return;
      stores.workflow.getState().pushExecutorError(p.node_id, p);
      const phaseTag = p.phase ? `[${p.phase}] ` : "";
      toast.error(
        `Agent "${p.agent_name}" ${phaseTag}failed (${p.error_type})`,
        {
          description: p.stderr_tail
            ? p.stderr_tail.slice(0, 200)
            : p.error_message,
        },
      );
    },
  ],

  [
    "agent.api_retry",
    (stores, event, _ctx) => {
      // P2-T4: transient retry in progress. Stash for live counter UI.
      // Filter on active workflow so background retries don't toast-spam.
      const p = payload<ApiRetryPayload>(event);
      stores.workflow.getState().pushApiRetry(p.node_id, p);
      // Low-key info toast: this is transient, not an error
      const currentWid = stores.workflow.getState().workflowId;
      const wfMatch = !event.payload?.workflow_id
        || currentWid === event.payload.workflow_id;
      if (wfMatch && p.retry_count !== undefined && p.max_retries !== undefined) {
        toast.info(
          `Agent "${p.agent_name}" retrying (${p.retry_count}/${p.max_retries})`,
          { description: p.error_message ?? "Transient upstream failure" },
        );
      }
    },
  ],

  [
    "agent.status_update",
    (stores, event, _ctx) => {
      // P2-T4: liveness status. No toast — drives spinner hint only.
      const p = payload<StatusUpdatePayload>(event);
      stores.workflow.getState().pushStatusUpdate(p.node_id, p);
    },
  ],
];
