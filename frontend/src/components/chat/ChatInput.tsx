"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useConversationStore, type ConversationMessage } from "@/stores/conversationStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Play, Square, Send } from "lucide-react";

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance?: (guidance: string) => void;
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
  sendGuidance,
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
  const [awaitingGuidance, setAwaitingGuidance] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isIdle = status === "idle";
  const isRunning = status === "running";

  const streamingAgent = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")) {
        return { agentName: m.agentName ?? m.nodeId ?? "agent", content: m.content, status: m.status };
      }
    }
    return null;
  })();

  const showStop = isRunning && !!sendStopAndRegenerate && !hasPendingQuestion && !awaitingGuidance;
  const showGuidanceInput = awaitingGuidance && !!sendGuidance;

  useEffect(() => {
    if (pendingQuestionId || canStartWorkflow) {
      inputRef.current?.focus();
    }
  }, [pendingQuestionId]);

  const canStartWorkflow = isIdle && !!selectedTemplate && !!startWorkflow;

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
    // Send stop signal with empty guidance → backend will await user guidance
    sendStopAndRegenerate(agentName, partialContent, "");
    // Switch to guidance input mode
    setAwaitingGuidance(true);
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, stopping, interruptMsg]);

  const handleGuidanceSubmit = useCallback(() => {
    const guidance = value.trim();
    if (!sendGuidance) return;
    // Send guidance to backend (wakes up the awaiting nodeFunc)
    sendGuidance(guidance || "继续");
    if (guidance) addUserMsg(guidance);
    setAwaitingGuidance(false);
    setStopping(false);
    setValue("");
  }, [value, sendGuidance, addUserMsg]);

  // Reset stopping when workflow stops running or a new agent starts streaming
  useEffect(() => {
    if (!isRunning) {
      setStopping(false);
      setAwaitingGuidance(false);
    }
  }, [isRunning]);

  // Reset awaitingGuidance when the streaming agent changes (retry started)
  useEffect(() => {
    if (isRunning && streamingAgent?.status === "streaming") {
      setAwaitingGuidance(false);
      setStopping(false);
    }
  }, [isRunning, streamingAgent?.agentName, streamingAgent?.status]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (showStop) {
          handleStop();
        } else if (showGuidanceInput) {
          handleGuidanceSubmit();
        } else {
          handleSend();
        }
      }
    },
    [showStop, showGuidanceInput, handleStop, handleGuidanceSubmit, handleSend]
  );

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !isRunning && !awaitingGuidance) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showGuidanceInput) return streamingAgent ? `输入指导给 ${streamingAgent.agentName} 继续...` : "输入指导继续生成...";
    if (showStop) return streamingAgent ? `点击 Stop 打断 ${streamingAgent.agentName}...` : "点击 Stop 停止运行...";
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
      ) : showGuidanceInput ? (
        <Button
          size="sm"
          onClick={handleGuidanceSubmit}
          className="h-8 shrink-0 gap-1 px-3 bg-emerald-600 hover:bg-emerald-700 text-white"
        >
          <Send className="h-3.5 w-3.5" />Send
        </Button>
      ) : (
        <Button
          size="sm"
          onClick={handleSend}
          disabled={!value.trim() && !canStartWorkflow}
          className="h-8 shrink-0 gap-1 px-3"
        >
          {canStartWorkflow ? <><Play className="h-3.5 w-3.5" />Start</> : "Send"}
        </Button>
      )}
    </div>
  );
}
