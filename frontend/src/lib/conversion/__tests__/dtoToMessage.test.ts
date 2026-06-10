/**
 * Tests for the DTO → UI message converter.
 *
 * These tests document the field-level defaults callers can rely on, so
 * future schema changes break loudly here instead of silently producing
 * weird UI state (e.g. a "running" tool status on a 6-month-old replayed
 * message).
 */

import { describe, it, expect } from "vitest";
import {
  dtoToMessage,
  dtoListToMessages,
  type ConversationMessageDTO,
} from "@/lib/conversion/dtoToMessage";

describe("dtoToMessage", () => {
  it("preserves agent message with content + nodeId", () => {
    const dto: ConversationMessageDTO = {
      id: "m1",
      type: "agent",
      nodeId: "writer",
      content: "hello world",
      agentName: "writer",
      status: "done",
      durationMs: 1234,
      timestamp: 1700000000000,
    };
    const m = dtoToMessage(dto, 0);
    expect(m.id).toBe("m1");
    expect(m.type).toBe("agent");
    expect(m.nodeId).toBe("writer");
    expect(m.content).toBe("hello world");
    expect(m.agentName).toBe("writer");
    expect(m.status).toBe("done");
    expect(m.durationMs).toBe(1234);
    expect(m.timestamp).toBe(1700000000000);
  });

  it("tool_call defaults toolStatus to 'done' when missing", () => {
    const dto: ConversationMessageDTO = {
      type: "tool_call",
      nodeId: "writer",
      toolName: "bash",
      toolArgs: { cmd: "ls" },
    };
    const m = dtoToMessage(dto, 0);
    expect(m.toolStatus).toBe("done");
  });

  it("preserves explicit toolStatus='running' if DTO sets it", () => {
    const dto: ConversationMessageDTO = {
      type: "tool_call",
      toolStatus: "running",
    };
    expect(dtoToMessage(dto, 0).toolStatus).toBe("running");
  });

  it("legacy run without thinking field yields undefined thinking", () => {
    const dto: ConversationMessageDTO = { type: "agent", content: "x" };
    expect(dtoToMessage(dto, 0).thinking).toBeUndefined();
  });

  it("content defaults to empty string when missing", () => {
    const dto: ConversationMessageDTO = { type: "agent" };
    expect(dtoToMessage(dto, 0).content).toBe("");
  });

  it("timestamp defaults to 0 when missing (legacy data)", () => {
    const dto: ConversationMessageDTO = { type: "system" };
    expect(dtoToMessage(dto, 0).timestamp).toBe(0);
  });

  it("synthesizes id from fallback index when DTO id is missing", () => {
    const dto: ConversationMessageDTO = { type: "agent", content: "x" };
    expect(dtoToMessage(dto, 7).id).toBe("replay-7");
  });

  it("unknown status string falls back to 'done'", () => {
    const dto: ConversationMessageDTO = { type: "agent", status: "wat" };
    expect(dtoToMessage(dto, 0).status).toBe("done");
  });

  it("missing status falls back to 'done'", () => {
    const dto: ConversationMessageDTO = { type: "agent" };
    expect(dtoToMessage(dto, 0).status).toBe("done");
  });

  it("preserves all known statuses", () => {
    const known: ConversationMessage["status"][] = [
      "streaming",
      "done",
      "error",
      "interrupted",
      "pending",
      "answered",
      "timeout",
    ];
    for (const s of known) {
      const dto: ConversationMessageDTO = { type: "agent", status: s };
      expect(dtoToMessage(dto, 0).status).toBe(s);
    }
  });

  it("preserves question-type fields", () => {
    const dto: ConversationMessageDTO = {
      type: "question",
      questionId: "q1",
      questionHeader: "Pick one",
      questionOptions: [{ label: "A", value: "a" }],
      questionMultiSelect: false,
      questionAllowCustomInput: true,
      questionInputType: "text",
      questionInputPlaceholder: "type here",
      questionAnswer: { selected: ["a"], customInput: "" },
    };
    const m = dtoToMessage(dto, 0);
    expect(m.type).toBe("question");
    expect(m.questionId).toBe("q1");
    expect(m.questionOptions).toEqual([{ label: "A", value: "a" }]);
    expect(m.questionAnswer).toEqual({ selected: ["a"], customInput: "" });
  });

  it("preserves followup marker", () => {
    const dto: ConversationMessageDTO = { type: "user", followup: true };
    expect(dtoToMessage(dto, 0).followup).toBe(true);
  });
});

describe("dtoListToMessages", () => {
  it("returns empty array for empty input", () => {
    expect(dtoListToMessages([])).toEqual([]);
  });

  it("maps each entry, preserving order", () => {
    const dtos: ConversationMessageDTO[] = [
      { id: "a", type: "user", content: "first" },
      { id: "b", type: "agent", content: "second" },
      { id: "c", type: "tool_call", toolName: "x" },
    ];
    const out = dtoListToMessages(dtos);
    expect(out).toHaveLength(3);
    expect(out.map((m) => m.id)).toEqual(["a", "b", "c"]);
    expect(out.map((m) => m.type)).toEqual(["user", "agent", "tool_call"]);
  });

  it("synthesizes stable ids for entries missing them, indexed by position", () => {
    const dtos: ConversationMessageDTO[] = [
      { type: "agent", content: "x" },
      { type: "agent", content: "y" },
    ];
    const out = dtoListToMessages(dtos);
    expect(out[0].id).toBe("replay-0");
    expect(out[1].id).toBe("replay-1");
  });

  it("round-trips a realistic mixed conversation", () => {
    const dtos: ConversationMessageDTO[] = [
      { id: "u1", type: "user", content: "Hello", timestamp: 1000 },
      { id: "a1", type: "agent", nodeId: "writer", agentName: "writer", content: "Hi", status: "done", timestamp: 1100 },
      { id: "t1", type: "tool_call", nodeId: "writer", toolName: "bash", toolArgs: { cmd: "pwd" }, toolResult: "/tmp", timestamp: 1200 },
    ];
    const out = dtoListToMessages(dtos);
    expect(out).toMatchSnapshot();
  });
});

// type-only import so TS keeps the union name in scope for the test above
import type { ConversationMessage } from "@/stores/conversationStore";
