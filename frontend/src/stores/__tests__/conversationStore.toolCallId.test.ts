/**
 * Tests for the tool_call_id-based matching fix (Bug 2).
 *
 * Reproduces the original bug: pydantic-ai emits BOTH function_tool_call
 * events before any result. Old matching (last-unmatched by name) lands
 * result A on call B. New matching keys on toolCallId so each result
 * lands on the correct message.
 */
import { describe, it, expect } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";

describe("createConversationStore — toolCallId matching", () => {
  it("addToolCall stamps toolCallId onto the new message", () => {
    const store = createConversationStore("wf-1");
    store.getState().addToolCall("scout", "scout", "bash", { cmd: "ls" }, "call_xyz");
    const msg = store.getState().messages.at(-1)!;
    expect(msg.type).toBe("tool_call");
    expect(msg.toolCallId).toBe("call_xyz");
  });

  it("addToolResult matches by toolCallId, not by (nodeId, toolName)", () => {
    const store = createConversationStore("wf-1");
    // Two parallel bash calls on the same node — same name, different IDs.
    store.getState().addToolCall("scout", "scout", "bash", { cmd: "ls" }, "A");
    store.getState().addToolCall("scout", "scout", "bash", { cmd: "pwd" }, "B");

    // Result for A arrives first.
    store.getState().addToolResult("A", "result-for-A");

    const msgs = store.getState().messages;
    const a = msgs.find((m) => m.toolCallId === "A")!;
    const b = msgs.find((m) => m.toolCallId === "B")!;
    expect(a.toolResult).toBe("result-for-A");
    // The bug would have written "result-for-A" onto B (the last pending
    // same-name call). B must still be result-less.
    expect(b.toolResult).toBeUndefined();
    expect(b.toolStatus).toBe("running");

    // Result for B arrives — lands on B only.
    store.getState().addToolResult("B", "result-for-B");
    const msgs2 = store.getState().messages;
    expect(msgs2.find((m) => m.toolCallId === "A")!.toolResult).toBe("result-for-A");
    expect(msgs2.find((m) => m.toolCallId === "B")!.toolResult).toBe("result-for-B");
  });

  it("addToolResult returns state unchanged when toolCallId has no match", () => {
    const store = createConversationStore("wf-1");
    store.getState().addToolCall("scout", "scout", "bash", { cmd: "ls" }, "A");
    const before = store.getState().messages;
    store.getState().addToolResult("UNKNOWN_ID", "orphan");
    expect(store.getState().messages).toBe(before);
  });

  it("addToolResult does not double-attach to an already-completed call", () => {
    const store = createConversationStore("wf-1");
    store.getState().addToolCall("scout", "scout", "bash", {}, "A");
    store.getState().addToolResult("A", "first");
    store.getState().addToolResult("A", "second");  // ignored
    const msg = store.getState().messages.find((m) => m.toolCallId === "A")!;
    expect(msg.toolResult).toBe("first");
  });

  it("appendToolOutput matches by toolCallId", () => {
    const store = createConversationStore("wf-1");
    store.getState().addToolCall("scout", "scout", "bash", {}, "A");
    store.getState().addToolCall("scout", "scout", "bash", {}, "B");

    store.getState().appendToolOutput("A", "hello", "stdout");
    const msgs = store.getState().messages;
    expect(msgs.find((m) => m.toolCallId === "A")!.toolStreamingOutput).toContain("hello");
    expect(msgs.find((m) => m.toolCallId === "B")!.toolStreamingOutput).toBeUndefined();
  });
});
