/**
 * Chat and followup event handlers.
 */

import type { EventHandler } from "./types";
import type { ChatQuestionPayload } from "@/types/events";
import { payload } from "./utils";

interface ChatAnswerPayload {
  workflow_id?: string;
  question_id: string;
  answer: string;
  raw?: { selected?: string[]; custom_input?: string; answer?: string };
}

interface ChatTimeoutPayload {
  workflow_id?: string;
  question_id: string;
  timeout_sec?: number | null;
}

function rawToAnswer(raw: ChatAnswerPayload["raw"]): { selected: string[]; customInput: string } | null {
  if (!raw) return null;
  // Legacy form: {answer: "..."} — store as customInput so the UI shows the text
  if (typeof raw.answer === "string" && !raw.selected) {
    return { selected: [], customInput: raw.answer };
  }
  return {
    selected: Array.isArray(raw.selected) ? raw.selected : [],
    customInput: typeof raw.custom_input === "string" ? raw.custom_input : "",
  };
}

export const chatHandlers: [string, EventHandler][] = [
  [
    "chat.question",
    (stores, event, _ctx) => {
      const p = payload<ChatQuestionPayload>(event);
      // Idempotent: skip if this question was already processed (WS replay guard)
      const alreadyExists = stores.conversation.getState().messages.some(
        (m) => m.type === "question" && m.questionId === p.question_id
      );
      if (alreadyExists) return;
      const conv = stores.conversation.getState();
      const lastStreaming = [...conv.messages]
        .reverse()
        .find((m) => m.type === "agent" && m.status === "streaming");
      const fallbackAgent = lastStreaming?.agentName ?? "agent";
      conv.addUserQuestion({
        question_id: p.question_id,
        question: p.question,
        agent_name: p.agent_name ?? fallbackAgent,
        node_id: p.node_id,
        header: p.header ?? null,
        options: p.options ?? null,
        multi_select: p.multi_select ?? false,
        allow_custom_input: p.allow_custom_input ?? true,
        input_type: p.input_type ?? "text",
        input_placeholder: p.input_placeholder ?? null,
      });
    },
  ],

  /**
   * chat.answer — backend emits this when ask_user resolves so late WS
   * subscribers (page refresh, new tab) see the resolved state via replay
   * instead of seeing only chat.question and re-prompting the user.
   *
   * chat.question is already in CRITICAL_EVENT_TYPES, so on reconnect the
   * replay order is question → answer; this handler marks the question
   * answered, and the chat.question idempotent guard then no-ops on the
   * already-answered message instead of inserting a duplicate.
   */
  [
    "chat.answer",
    (stores, event, _ctx) => {
      const p = payload<ChatAnswerPayload>(event);
      const conv = stores.conversation.getState();
      const existing = conv.messages.find(
        (m) => m.type === "question" && m.questionId === p.question_id,
      );
      if (!existing) {
        // Late-arriving answer with no matching question (already finalized
        // by markAllPendingQuestionsInterrupted, or race with a new subscriber).
        // Drop silently — the question was either resolved or no longer relevant.
        return;
      }
      if (existing.status === "answered") return; // idempotent
      const structured = rawToAnswer(p.raw);
      if (structured) {
        conv.answerUserQuestion(p.question_id, structured);
      } else {
        // No raw payload — fall back to the assembled answer string as customInput
        conv.answerUserQuestion(p.question_id, { selected: [], customInput: p.answer });
      }
      conv.clearPendingQuestion(p.question_id);
    },
  ],

  /**
   * chat.timeout — emitted when ask_user's wait future expires. Marks the
   * question timed_out so the UI doesn't keep showing a live prompt that
   * can no longer be answered. Idempotent on already-finalized questions.
   */
  [
    "chat.timeout",
    (stores, event, _ctx) => {
      const p = payload<ChatTimeoutPayload>(event);
      const conv = stores.conversation.getState();
      const existing = conv.messages.find(
        (m) => m.type === "question" && m.questionId === p.question_id,
      );
      if (!existing || existing.status !== "pending") return;
      conv.markQuestionTimeout(p.question_id);
      conv.clearPendingQuestion(p.question_id);
    },
  ],

  [
    "followup.started",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; turn: number }>(event);
      const conv = stores.conversation.getState();
      conv.addFollowupAgentMessage(p.agent_name);
    },
  ],

  [
    "followup.completed",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; turn: number }>(event);
      const nodeId = `followup-${p.agent_name}`;
      stores.conversation.getState().completeAgentMessage(nodeId, p.agent_name);
    },
  ],

  [
    "followup.failed",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; error: string }>(event);
      const nodeId = `followup-${p.agent_name}`;
      stores.conversation.getState().failAgentMessage(nodeId, p.agent_name, p.error);
    },
  ],
];
