"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useConversationStore, type ConversationMessage } from "@/stores/conversationStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Play, Square, Send, AtSign } from "lucide-react";

interface AgentOption {
  name: string;
  model?: string | null;
}

interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance?: (guidance: string) => void;
  sendFollowup?: (agentName: string, question: string) => void;
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
  agentsSnapshot?: AgentOption[];
}

export default function ChatInput({
  sendAnswer,
  sendStopAndRegenerate,
  sendGuidance,
  sendFollowup,
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
  agentsSnapshot: propAgents,
}: ChatInputProps) {
  // Always call global store hooks (React rules of hooks)
  const globalPendingId = useConversationStore((s) => s.pendingQuestionId);
  const globalPendingAgent = useConversationStore((s) => s.pendingQuestionAgent);
  const globalMessages = useConversationStore((s) => s.messages);
  const globalStatus = useWorkflowStore((s) => s.status);
  const globalWid = useWorkflowStore((s) => s.workflowId);
  const globalTemplate = useWorkflowStore((s) => s.selectedTemplate);
  const activeFollowupAgent = useConversationStore((s) => s.activeFollowupAgent);
  const setActiveFollowupAgent = useConversationStore((s) => s.setActiveFollowupAgent);
  const addFollowupUserMessage = useConversationStore((s) => s.addFollowupUserMessage);

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
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  const isIdle = status === "idle";
  const isRunning = status === "running";
  const isCompleted = status === "completed" || status === "failed";
  const isFollowupMode = isCompleted && !!sendFollowup;

  // Agent list for @mention — try prop first, then run history
  const runHistory = useRunHistoryStore();
  const agents: AgentOption[] = useMemo(() => {
    if (propAgents && propAgents.length > 0) return propAgents;
    // Fallback: get agents from run record
    const runId = workflowId;
    if (!runId) return [];
    const full = runHistory.runs.find((r) => r.run_id === runId);
    // Can't easily get agents from summary — will be populated via prop
    return [];
  }, [propAgents, workflowId, runHistory.runs]);

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
    if (pendingQuestionId || canStartWorkflow || isFollowupMode) {
      inputRef.current?.focus();
    }
  }, [pendingQuestionId, isFollowupMode]);

  // Close agent picker on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setShowAgentPicker(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const canStartWorkflow = isIdle && !!selectedTemplate && !!startWorkflow;

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;

    if (hasPendingQuestion) {
      sendAnswer(pendingQuestionId, trimmed);
      addUserMsg(trimmed);
      clearPQ(pendingQuestionId);
    } else if (isFollowupMode && activeFollowupAgent) {
      // Send followup to the active agent
      addFollowupUserMessage(activeFollowupAgent, trimmed);
      sendFollowup(activeFollowupAgent, trimmed);
    } else if (canStartWorkflow) {
      startWorkflow(selectedTemplate, trimmed);
    }
    setValue("");
  }, [value, pendingQuestionId, hasPendingQuestion, sendAnswer, startWorkflow, selectedTemplate, canStartWorkflow, addUserMsg, clearPQ, isFollowupMode, activeFollowupAgent, sendFollowup, addFollowupUserMessage]);

  const handleStop = useCallback(async () => {
    if (!sendStopAndRegenerate || stopping) return;
    setStopping(true);
    const agentName = streamingAgent?.agentName ?? "";
    const partialContent = streamingAgent?.content ?? "";
    if (streamingAgent) {
      interruptMsg(agentName);
    }
    sendStopAndRegenerate(agentName, partialContent, "");
    setAwaitingGuidance(true);
    setValue("");
  }, [streamingAgent, sendStopAndRegenerate, stopping, interruptMsg]);

  const handleGuidanceSubmit = useCallback(() => {
    const guidance = value.trim();
    if (!sendGuidance) return;
    sendGuidance(guidance || "继续");
    if (guidance) addUserMsg(guidance);
    setAwaitingGuidance(false);
    setStopping(false);
    setValue("");
  }, [value, sendGuidance, addUserMsg]);

  // Reset when workflow stops running
  useEffect(() => {
    if (!isRunning) {
      setStopping(false);
      setAwaitingGuidance(false);
    }
  }, [isRunning]);

  // @mention detection
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setValue(val);

    if (!isFollowupMode) return;

    // Detect @trigger
    const lastAtIndex = val.lastIndexOf("@");
    if (lastAtIndex !== -1) {
      const afterAt = val.slice(lastAtIndex + 1);
      // Only show picker if @ is at start or preceded by space
      const isAtTrigger = lastAtIndex === 0 || val[lastAtIndex - 1] === " ";
      if (isAtTrigger && !afterAt.includes(" ")) {
        setShowAgentPicker(true);
        setMentionFilter(afterAt.toLowerCase());
        return;
      }
    }
    setShowAgentPicker(false);
  }, [isFollowupMode]);

  const handleSelectAgent = useCallback((agent: AgentOption) => {
    setActiveFollowupAgent(agent.name);
    setShowAgentPicker(false);
    setValue("");
    inputRef.current?.focus();
  }, [setActiveFollowupAgent]);

  const filteredAgents = useMemo(() => {
    if (!mentionFilter) return agents;
    return agents.filter((a) => a.name.toLowerCase().includes(mentionFilter));
  }, [agents, mentionFilter]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (showAgentPicker && e.key === "Escape") {
        setShowAgentPicker(false);
        return;
      }
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
    [showStop, showGuidanceInput, handleStop, handleGuidanceSubmit, handleSend, showAgentPicker]
  );

  if (!alwaysVisible && !hasPendingQuestion && !canStartWorkflow && !isRunning && !awaitingGuidance && !isFollowupMode) return null;

  const getPlaceholder = () => {
    if (hasPendingQuestion && pendingQuestionAgent) return `回答 ${pendingQuestionAgent} 的问题...`;
    if (canStartWorkflow) return `输入任务启动 ${(selectedTemplate as Record<string, unknown>).name as string}...`;
    if (showGuidanceInput) return streamingAgent ? `输入指导给 ${streamingAgent.agentName} 继续...` : "输入指导继续生成...";
    if (showStop) return streamingAgent ? `点击 Stop 打断 ${streamingAgent.agentName}...` : "点击 Stop 停止运行...";
    if (isFollowupMode && activeFollowupAgent) return `追问 ${activeFollowupAgent}...`;
    if (isFollowupMode) return "@ 选择 Agent 追问...";
    return "Message...";
  };

  return (
    <div className="relative flex items-center gap-2 border-t border-app-border px-3 py-2 bg-background">
      {/* Agent picker popup */}
      {showAgentPicker && filteredAgents.length > 0 && (
        <div
          ref={pickerRef}
          className="absolute bottom-full left-3 mb-1 z-50 max-h-48 w-56 overflow-auto rounded-md border border-app-border bg-popover shadow-lg"
        >
          {filteredAgents.map((agent) => (
            <button
              key={agent.name}
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left"
              onClick={() => handleSelectAgent(agent)}
            >
              <AtSign className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span className="truncate">{agent.name}</span>
              {agent.model && (
                <span className="ml-auto text-xs text-muted-foreground truncate max-w-[80px]">{agent.model}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Follow-up agent indicator */}
      {isFollowupMode && activeFollowupAgent && (
        <div className="flex items-center gap-1 shrink-0 rounded-md bg-blue-500/10 px-2 py-0.5 text-xs text-blue-600">
          <AtSign className="h-3 w-3" />
          {activeFollowupAgent}
          <button
            type="button"
            className="ml-1 text-blue-400 hover:text-blue-600"
            onClick={() => setActiveFollowupAgent(null)}
            aria-label="Clear agent selection"
          >
            ×
          </button>
        </div>
      )}

      <Input
        ref={inputRef}
        value={value}
        onChange={handleInputChange}
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
          disabled={!value.trim() && !canStartWorkflow && !(isFollowupMode && activeFollowupAgent)}
          className="h-8 shrink-0 gap-1 px-3"
        >
          {canStartWorkflow ? <><Play className="h-3.5 w-3.5" />Start</> : "Send"}
        </Button>
      )}
    </div>
  );
}
