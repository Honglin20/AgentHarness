import { describe, it, expectTypeOf } from "vitest";
import type { ConversationMessage } from "@/stores/conversationStore";

describe("ConversationMessage", () => {
  it("has optional iteration field (number | undefined)", () => {
    const m1: ConversationMessage = {
      id: "msg-1",
      type: "agent",
      content: "",
      timestamp: 0,
    };
    const m2: ConversationMessage = {
      id: "msg-2",
      type: "agent",
      content: "",
      timestamp: 0,
      iteration: 2,
    };
    expectTypeOf(m1.iteration).toEqualTypeOf<number | undefined>();
    expectTypeOf(m2.iteration).toEqualTypeOf<number | undefined>();
  });
});
