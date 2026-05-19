"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
}

export default function ChatInput({ sendAnswer }: ChatInputProps) {
  const pendingQuestionId = useChatStore((s) => s.pendingQuestionId);
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus when pending question appears
  useEffect(() => {
    if (pendingQuestionId) {
      inputRef.current?.focus();
    }
  }, [pendingQuestionId]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !pendingQuestionId || sending) return;

    setSending(true);
    sendAnswer(pendingQuestionId, trimmed);
    setValue("");
    // Brief disabled state — re-enable on next tick
    requestAnimationFrame(() => setSending(false));
  }, [value, pendingQuestionId, sending, sendAnswer]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  if (!pendingQuestionId) return null;

  return (
    <div className="flex items-center gap-2 border-t border-app-border px-3 py-2">
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type your answer..."
        disabled={sending}
        className="h-8 text-sm"
      />
      <Button
        size="sm"
        onClick={handleSubmit}
        disabled={sending || !value.trim()}
        className="h-8 shrink-0 px-3"
      >
        Send
      </Button>
    </div>
  );
}
