/**
 * Agent streaming event handlers.
 */

import type { EventHandler } from "./types";
import type {
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentThinkingDeltaPayload,
  AgentToolOutputDeltaPayload,
  AgentToolOutputTruncatedPayload,
  BashBackgroundCompletedPayload,
} from "@/types/events";
import { payload } from "./utils";

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
];
