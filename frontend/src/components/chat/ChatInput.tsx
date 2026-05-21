"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Play, Zap } from "lucide-react";

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendInterrupt?: (directive: string) => void;
  startWorkflow?: (template: unknown, task: string) => void;
  alwaysVisible?: boolean;
}

export default function ChatInput({ sendAnswer, sendInterrupt, startWorkflow, alwaysVisible = false }: ChatInputProps) {
  const pendingQuestionId = useConversationStore((s) => s.pendingQuestionId);
  const pendingQuestionAgent = useConversationStore((s) => s.pendingQuestionAgent);
  const hasPendingQuestion = pendingQuestionId !== null;
  const status = useWorkflowStore((s) => s.status);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isIdle = status === "idle";
  const isRunning = status === "running";
  const canStartWorkflow = isIdle && !!selectedTemplate && !!startWorkflow;

  useEffect(() => {
    if (pendingQuestionId || canStartWorkflow) {
      inputRef.current?.focus();
    }
  }, [pendingQuestionId, canStartWorkflow]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;

    if (hasPendingQuestion) {
      sendAnswer(pendingQuestionId, trimmed);
      useConversationStore.getState().addUserMessage(trimmed);
      useConversationStore.getState().clearPendingQuestion(pendingQuestionId);
    } else if (canStartWorkflow) {
      startWorkflow(selectedTemplate, trimmed);
    } else if (isRunning && sendInterrupt) {
      sendInterrupt(trimmed);
      useConversationStore.getState().addUserMessage(trimmed);
    }
    setValue("");
  }, [value, pendingQuestionId, hasPendingQuestion, isRunning, sendAnswer, sendInterrupt, startWorkflow, selectedTemplate, canStartWorkflow]);

  const handleInterrupt = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !sendInterrupt) return;
    sendInterrupt(trimmed);
    setValue("");
  }, [value, sendInterrupt]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    return "Message...";
  };

  return (
    <div className="flex items-center gap-2 border-t border-app-border px-3 py-2 bg-white">
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={getPlaceholder()}
        aria-label={hasPendingQuestion ? "Type your answer" : "Type a message"}
        className={hasPendingQuestion ? "h-8 text-sm ring-2 ring-blue-500" : "h-8 text-sm"}
      />
      <Button
        size="sm"
        onClick={handleSubmit}
        disabled={!value.trim()}
        className="h-8 shrink-0 gap-1 px-3"
      >
        {canStartWorkflow ? <><Play className="h-3.5 w-3.5" />Start</> : "Send"}
      </Button>
      {isRunning && sendInterrupt && !hasPendingQuestion && (
        <Button
          size="sm"
          variant="destructive"
          onClick={handleInterrupt}
          disabled={!value.trim()}
          className="h-8 shrink-0 gap-1 px-3"
        >
          <Zap className="h-3.5 w-3.5" />
          Interrupt
        </Button>
      )}
    </div>
  );
}
