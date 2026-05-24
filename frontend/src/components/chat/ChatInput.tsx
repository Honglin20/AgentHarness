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

  const isRunning = status === "running";
  const showStop = isRunning && !!sendStopAndRegenerate && !hasPendingQuestion;

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
    if (!sendStopAndRegenerate) return;
    const agentName = streamingAgent?.agentName ?? "";
    const partialContent = streamingAgent?.content ?? "";
    if (streamingAgent) {
      useConversationStore.getState().interruptAgentMessage(agentName);
    }
    // Send empty guidance = just stop, no regenerate
    sendStopAndRegenerate(agentName, partialContent, "");
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate]);

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

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !isRunning) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showStop) return streamingAgent ? `指导 ${streamingAgent.agentName} 重新生成（可留空直接停止）...` : "点击 Stop 停止运行...";
    return "Message...";
  };

  return (
    <div className="flex items-center gap-2 border-t border-app-border px-3 py-2 bg-background">
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
          onClick={handleStop}
          className="h-8 w-8 shrink-0 rounded-full bg-red-600 hover:bg-red-700 text-white p-0"
          aria-label="Stop"
        >
          <Square className="h-3 w-3 fill-current" />
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
