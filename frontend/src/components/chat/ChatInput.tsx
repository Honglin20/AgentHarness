"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useConversationStore, type ConversationMessage } from "@/stores/conversationStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { fetchWithAuth } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Play, Square } from "lucide-react";

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  startWorkflow?: (template: unknown, task: string) => void;
  alwaysVisible?: boolean;
  // Optional scoped store overrides (Context architecture)
  pendingQuestionId?: string | null;
  pendingQuestionAgent?: string | null;
  messages?: ConversationMessage[];
  addUserMessage?: (text: string) => void;
  clearPendingQuestion?: (id: string) => void;
  interruptAgentMessage?: (name: string) => void;
  status?: string;
  workflowId?: string | null;
  selectedTemplate?: unknown;
}

export default function ChatInput({
  sendAnswer,
  sendStopAndRegenerate,
  startWorkflow,
  alwaysVisible = false,
  pendingQuestionId: propPendingId,
  pendingQuestionAgent: propPendingAgent,
  messages: propMessages,
  addUserMessage: propAddUserMsg,
  clearPendingQuestion: propClearPQ,
  interruptAgentMessage: propInterrupt,
  status: propStatus,
  workflowId: propWid,
  selectedTemplate: propTemplate,
}: ChatInputProps) {
  // Always call global store hooks (React rules of hooks)
  const globalPendingId = useConversationStore((s) => s.pendingQuestionId);
  const globalPendingAgent = useConversationStore((s) => s.pendingQuestionAgent);
  const globalMessages = useConversationStore((s) => s.messages);
  const globalStatus = useWorkflowStore((s) => s.status);
  const globalWid = useWorkflowStore((s) => s.workflowId);
  const globalTemplate = useWorkflowStore((s) => s.selectedTemplate);

  // Use scoped props when provided, otherwise fall back to global stores
  const pendingQuestionId = propPendingId !== undefined ? propPendingId : globalPendingId;
  const pendingQuestionAgent = propPendingAgent !== undefined ? propPendingAgent : globalPendingAgent;
  const messages = propMessages !== undefined ? propMessages : globalMessages;
  const status = propStatus !== undefined ? propStatus : globalStatus;
  const workflowId = propWid !== undefined ? propWid : globalWid;
  const selectedTemplate = propTemplate !== undefined ? propTemplate : globalTemplate;

  const addUserMsg = useMemo(
    () => propAddUserMsg ?? ((text: string) => useConversationStore.getState().addUserMessage(text)),
    [propAddUserMsg]
  );
  const clearPQ = useMemo(
    () => propClearPQ ?? ((id: string) => useConversationStore.getState().clearPendingQuestion(id)),
    [propClearPQ]
  );
  const interruptMsg = useMemo(
    () => propInterrupt ?? ((name: string) => useConversationStore.getState().interruptAgentMessage(name)),
    [propInterrupt]
  );

  const hasPendingQuestion = pendingQuestionId !== null;
  const [value, setValue] = useState("");
  const [stopping, setStopping] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isIdle = status === "idle";
  const isRunning = status === "running";
  const isPaused = status === "paused";
  const isInterrupted = status === "interrupted";
  const canStartWorkflow = isIdle && !!selectedTemplate && !!startWorkflow;

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
  const showPausedInput = (isPaused || isInterrupted) && !!sendStopAndRegenerate;

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
      addUserMsg(trimmed);
      clearPQ(pendingQuestionId);
    } else if (canStartWorkflow) {
      startWorkflow(selectedTemplate, trimmed);
    }
    setValue("");
  }, [value, pendingQuestionId, hasPendingQuestion, sendAnswer, startWorkflow, selectedTemplate, canStartWorkflow, addUserMsg, clearPQ]);

  const handleStop = useCallback(async () => {
    if (!sendStopAndRegenerate || stopping) return;
    setStopping(true);
    const agentName = streamingAgent?.agentName ?? "";
    const partialContent = streamingAgent?.content ?? "";
    if (streamingAgent) {
      interruptMsg(agentName);
    }
    sendStopAndRegenerate(agentName, partialContent, "");
    // Keep stopping=true until workflow status or streaming agent changes
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, stopping, interruptMsg]);

  // Reset stopping when workflow stops running or a new agent starts streaming
  useEffect(() => {
    setStopping(false);
  }, [isRunning, streamingAgent?.agentName]);

  const handlePausedSubmit = useCallback(async () => {
    const guidance = value.trim();
    if (!workflowId) return;
    if (guidance) addUserMsg(guidance);
    try {
      await fetchWithAuth(`/api/runs/${workflowId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guidance: guidance || null }),
      });
    } catch {
      // best effort
    }
    setValue("");
  }, [value, workflowId, addUserMsg]);

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

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !isRunning && !isPaused && !isInterrupted) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showPausedInput) return isInterrupted
      ? (streamingAgent ? `输入指导给 ${streamingAgent.agentName} 继续生成...` : "输入指导继续生成...")
      : (streamingAgent ? `输入指导给 ${streamingAgent.agentName}，或直接回车继续...` : "输入指导或直接回车继续...");
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
