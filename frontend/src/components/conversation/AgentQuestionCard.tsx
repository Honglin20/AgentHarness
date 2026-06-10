"use client";

import React, { useMemo, useState } from "react";
import { CheckCircle2, Clock, HelpCircle, PauseCircle } from "lucide-react";

import { MarkdownText } from "@/components/conversation/MarkdownText";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ConversationMessage, QuestionOption } from "@/stores/conversationStore";

interface AgentQuestionCardProps {
  message: ConversationMessage;
  onSubmit: (answer: { selected: string[]; customInput: string }) => void;
  /**
   * Compact read-only rendering. When true, the card shows only the
   * header row (icon + agent + question first line + status badge) and
   * skips interactive controls, full options, and the answer detail
   * block.
   *
   * Defaults to ``false`` (always expanded) so users can see ask_user
   * calls even after they have been answered — R7 fix, see ADR
   * ``docs/plans/2026-06-10-todo-step-gate-adr.md``. Callers may pass
   * ``true`` to force compact (e.g. inside a collapsed NodeBlock).
   */
  collapsed?: boolean | "auto";
}

function optionValue(opt: QuestionOption): string {
  return opt.value ?? opt.label;
}

function answerSummary(
  options: QuestionOption[] | null | undefined,
  answer: { selected: string[]; customInput: string },
): string {
  const valueToLabel = new Map<string, string>();
  (options ?? []).forEach((o) => {
    valueToLabel.set(optionValue(o), o.label);
  });
  const labels = answer.selected.map((v) => valueToLabel.get(v) ?? v);
  const left = labels.join(", ");
  if (left && answer.customInput) return `${left} | other: ${answer.customInput}`;
  return left || answer.customInput;
}

export const AgentQuestionCard = React.memo(function AgentQuestionCard({ message, onSubmit, collapsed = false }: AgentQuestionCardProps) {
  const {
    questionOptions: options,
    questionMultiSelect: multiSelect = false,
    questionAllowCustomInput: allowCustomInput = true,
    questionInputType: inputType = "text",
    questionInputPlaceholder,
    questionHeader,
    questionAnswer,
    status,
    agentName,
    content: question,
  } = message;

  const isAnswered = status === "answered";
  const isTimeout = status === "timeout";
  const isPending = status === "pending";
  const isInterrupted = status === "interrupted";

  const [selected, setSelected] = useState<string[]>([]);
  const [customInput, setCustomInput] = useState("");

  const hasOptions = !!options && options.length > 0;
  // If there are no options at all, the free-form input becomes the
  // primary control regardless of allow_custom_input.
  const showCustomInput = !hasOptions || allowCustomInput;

  const canSubmit = useMemo(() => {
    if (!isPending) return false;
    return selected.length > 0 || customInput.trim().length > 0;
  }, [isPending, selected, customInput]);

  const toggleOption = (val: string) => {
    if (!isPending) return;
    if (multiSelect) {
      setSelected((prev) =>
        prev.includes(val) ? prev.filter((v) => v !== val) : [...prev, val],
      );
    } else {
      setSelected((prev) => (prev[0] === val ? [] : [val]));
    }
  };

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({
      selected,
      customInput: showCustomInput ? customInput.trim() : "",
    });
  };

  const Icon = isAnswered ? CheckCircle2 : isTimeout ? Clock : isInterrupted ? PauseCircle : HelpCircle;
  const accent = isAnswered
    ? "border-emerald-500/40 bg-emerald-500/5"
    : isTimeout
    ? "border-muted-foreground/30 bg-muted/30"
    : isInterrupted
    ? "border-muted-foreground/30 bg-muted/30"
    : "border-amber-500/50 bg-amber-500/5";

  // Compact mode = explicit `true` OR auto + non-pending. Renders a single
  // line (icon + first line of question + trailing status / answer summary)
  // and skips the full options / custom input / detail blocks.
  const isCompact = collapsed === true || (collapsed === "auto" && !isPending);

  if (isCompact) {
    const firstLine = (question ?? "").split("\n").find((l) => l.trim()) ?? "(empty question)";
    const tail = isAnswered && questionAnswer
      ? `→ ${answerSummary(options, questionAnswer) || "(空)"}`
      : isTimeout
      ? "→ 已超时"
      : isInterrupted
      ? "→ 未回答"
      : "";
    return (
      <div className={cn("rounded-xl border-l-4 px-3 py-1.5", accent)}>
        <div className="flex items-center gap-2 text-xs">
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              isAnswered ? "text-emerald-500" : isTimeout ? "text-muted-foreground" : "text-amber-500",
            )}
          />
          <span className="min-w-0 flex-1 truncate font-medium">{firstLine}</span>
          {tail && <span className="shrink-0 text-muted-foreground">{tail}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={cn("rounded-xl border-l-4 p-4", accent)}>
      <div className="mb-2 flex items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            isAnswered ? "text-emerald-500" : isTimeout ? "text-muted-foreground" : "text-amber-500",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {questionHeader && (
              <span className="rounded-md bg-muted px-2 py-0.5 font-medium uppercase tracking-wide">
                {questionHeader}
              </span>
            )}
            <span>{agentName ?? "agent"} 想请你确认</span>
            {isAnswered && <span className="text-emerald-600">已回答</span>}
            {isTimeout && <span>已超时</span>}
            {isInterrupted && <span>运行已结束，未回答</span>}
          </div>
          <MarkdownText className="font-medium leading-snug">{question}</MarkdownText>
        </div>
      </div>

      {/* Answered state — show summary only */}
      {isAnswered && questionAnswer && (
        <div className="ml-7 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">你的回答：</span>
          {answerSummary(options, questionAnswer) || "(空)"}
        </div>
      )}

      {/* Pending state — interactive controls. Below the early compact-mode
       * return, we only get here when collapsed is false or auto+pending,
       * so the original `!collapsed` guard is implied. */}
      {isPending && (
        <div className="ml-7 space-y-3">
          {hasOptions && (
            <div className="flex flex-wrap gap-2">
              {options!.map((opt) => {
                const val = optionValue(opt);
                const active = selected.includes(val);
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => toggleOption(val)}
                    className={cn(
                      "flex max-w-full items-start gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                      active
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-input bg-background hover:bg-muted",
                    )}
                  >
                    <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center">
                      {multiSelect ? (
                        <span
                          className={cn(
                            "h-3 w-3 rounded-sm border",
                            active
                              ? "border-primary-foreground bg-primary-foreground"
                              : "border-muted-foreground",
                          )}
                        />
                      ) : (
                        <span
                          className={cn(
                            "h-3 w-3 rounded-full border",
                            active
                              ? "border-primary-foreground bg-primary-foreground"
                              : "border-muted-foreground",
                          )}
                        />
                      )}
                    </span>
                    <span className="min-w-0">
                      <div className="font-medium">{opt.label}</div>
                      {opt.description && (
                        <div
                          className={cn(
                            "mt-0.5 text-[11px] leading-snug",
                            active ? "text-primary-foreground/80" : "text-muted-foreground",
                          )}
                        >
                          {opt.description}
                        </div>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {showCustomInput && (
            <div>
              {hasOptions && (
                <label className="mb-1 block text-[11px] uppercase tracking-wide text-muted-foreground">
                  其他 / 补充
                </label>
              )}
              {inputType === "textarea" ? (
                <textarea
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  placeholder={questionInputPlaceholder ?? "请输入..."}
                  rows={3}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              ) : (
                <input
                  type={inputType}
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  placeholder={questionInputPlaceholder ?? "请输入..."}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && canSubmit) {
                      e.preventDefault();
                      handleSubmit();
                    }
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              )}
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button size="sm" disabled={!canSubmit} onClick={handleSubmit}>
              提交
            </Button>
          </div>
        </div>
      )}

      {isTimeout && (
        <div className="ml-7 text-xs text-muted-foreground">
          用户未在规定时间内回答，agent 已使用默认判断继续。
        </div>
      )}
    </div>
  );
});
