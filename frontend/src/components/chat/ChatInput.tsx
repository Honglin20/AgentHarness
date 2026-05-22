"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Play, Square } from "lucide-react";

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  startWorkflow?: (template: unknown, task: string) => void;
  alwaysVisible?: boolean;
}

export default function ChatInput({ sendAnswer, sendStopAndRegenerate, startWorkflow, alwaysVisible = false }: ChatInputProps) {
  const pendingQuestionId = useConversationStore((s) => s.pendingQuestionId);
  const pendingQuestionAgent = useConversationStore((s) => s.pendingQuestionAgent);
  const messages = useConversationStore((s) => s.messages);
  const hasPendingQuestion = pendingQuestionId !== null;
  const status = useWorkflowStore((s) => s.status);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isIdle = status === "idle";
  const canStartWorkflow = isIdle && !!selectedTemplate && !!startWorkflow;

  // Find the most recent agent message that's still streaming or interrupted
  const streamingAgent = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")) {
        return { agentName: m.agentName ?? m.nodeId ?? "agent", content: m.content, status: m.status };
      }
    }
    return null;
  })();

  const showStop = !!streamingAgent && streamingAgent.status === "streaming" && !!sendStopAndRegenerate && !hasPendingQuestion;

  useEffect(() => {
    if (pendingQuestionId || canStartWorkflow) {
      inputRef.current?.focus();
    }
  }, [pendingQuestionId, canStartWorkflow]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;

    if (hasPendingQuestion) {
      sendAnswer(pendingQuestionId, trimmed);
      useConversationStore.getState().addUserMessage(trimmed);
      useConversationStore.getState().clearPendingQuestion(pendingQuestionId);
    } else if (canStartWorkflow) {
      startWorkflow(selectedTemplate, trimmed);
    }
    setValue("");
  }, [value, pendingQuestionId, hasPendingQuestion, sendAnswer, startWorkflow, selectedTemplate, canStartWorkflow]);

  const handleStop = useCallback(() => {
    if (!streamingAgent || !sendStopAndRegenerate) return;
    // Immediately mark agent as interrupted locally to prevent race conditions
    useConversationStore.getState().interruptAgentMessage(streamingAgent.agentName);
    sendStopAndRegenerate(streamingAgent.agentName, streamingAgent.content, value);
    if (value.trim()) {
      useConversationStore.getState().addUserMessage(value);
    }
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, value]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (showStop) {
          handleStop();
        } else {
          handleSend();
        }
      }
    },
    [showStop, handleStop, handleSend]
  );

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !showStop) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showStop) return `指导 ${streamingAgent!.agentName} 重新生成（可留空直接停止）...`;
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
      {showStop ? (
        <Button
          size="sm"
          variant="destructive"
          onClick={handleStop}
          className="h-8 shrink-0 gap-1 px-3"
          aria-label="Stop and regenerate"
        >
          <Square className="h-3.5 w-3.5 fill-current" />
          Stop
        </Button>
      ) : (
        <Button
          size="sm"
          onClick={handleSend}
          disabled={!value.trim()}
          className="h-8 shrink-0 gap-1 px-3"
        >
          {canStartWorkflow ? <><Play className="h-3.5 w-3.5" />Start</> : "Send"}
        </Button>
      )}
    </div>
  );
}
