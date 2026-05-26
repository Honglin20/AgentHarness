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
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const [value, setValue] = useState("");
  const [stopping, setStopping] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isIdle = status === "idle";
  const isRunning = status === "running";
  const isPaused = status === "paused";
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

  const showStop = isRunning && !!sendStopAndRegenerate && !hasPendingQuestion;
  const showPausedInput = isPaused && !!sendStopAndRegenerate;

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

  const handleStop = useCallback(async () => {
    if (!sendStopAndRegenerate || stopping) return;
    setStopping(true);
    const agentName = streamingAgent?.agentName ?? "";
    const partialContent = streamingAgent?.content ?? "";
    if (streamingAgent) {
      useConversationStore.getState().interruptAgentMessage(agentName);
    }
    // Send stop signal to interrupt the agent
    sendStopAndRegenerate(agentName, partialContent, "");
    // Also pause the workflow to prevent it from jumping to the next agent
    if (workflowId) {
      try {
        await fetch(`/api/workflows/${workflowId}/cancel`, { method: "POST" });
      } catch {
        // best effort
      }
    }
    setStopping(false);
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, workflowId, stopping]);

  // Handle guidance submission while paused
  const handlePausedSubmit = useCallback(async () => {
    const guidance = value.trim();
    if (!workflowId) return;
    const agentName = streamingAgent?.agentName ?? "";
    // If user typed guidance, send it as stop_and_regenerate before resuming
    if (guidance && sendStopAndRegenerate) {
      sendStopAndRegenerate(agentName, streamingAgent?.content ?? "", guidance);
      useConversationStore.getState().addUserMessage(guidance);
    }
    // Resume the workflow
    try {
      await fetch(`/api/runs/${workflowId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
    } catch {
      // best effort
    }
    setValue("");
  }, [value, workflowId, streamingAgent, sendStopAndRegenerate]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (showStop) {
          handleStop();
        } else if (showPausedInput) {
          handlePausedSubmit();
        } else {
          handleSend();
        }
      }
    },
    [showStop, showPausedInput, handleStop, handlePausedSubmit, handleSend]
  );

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !isRunning && !isPaused) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showPausedInput) return streamingAgent ? `输入指导给 ${streamingAgent.agentName}，或直接回车继续...` : "输入指导或直接回车继续...";
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
          disabled={stopping}
          className="h-8 w-8 shrink-0 rounded-full bg-red-600 hover:bg-red-700 text-white p-0 disabled:opacity-60"
          aria-label="Stop"
        >
          <Square className="h-3 w-3 fill-current" />
        </Button>
      ) : showPausedInput ? (
        <Button
          size="sm"
          onClick={handlePausedSubmit}
          className="h-8 shrink-0 gap-1 px-3 bg-emerald-600 hover:bg-emerald-700 text-white"
        >
          <Play className="h-3.5 w-3.5" />Resume
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
