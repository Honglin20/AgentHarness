"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Clock, HelpCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ConversationMessage, QuestionOption } from "@/stores/conversationStore";

interface AgentQuestionCardProps {
  message: ConversationMessage;
  onSubmit: (answer: { selected: string[]; customInput: string }) => void;
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

export function AgentQuestionCard({ message, onSubmit }: AgentQuestionCardProps) {
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

  const Icon = isAnswered ? CheckCircle2 : isTimeout ? Clock : HelpCircle;
  const accent = isAnswered
    ? "border-emerald-500/40 bg-emerald-500/5"
    : isTimeout
    ? "border-muted-foreground/30 bg-muted/30"
    : "border-amber-500/50 bg-amber-500/5";

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
          </div>
          <div className="text-sm font-medium leading-snug">{question}</div>
        </div>
      </div>

      {/* Answered state — show summary only */}
      {isAnswered && questionAnswer && (
        <div className="ml-7 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">你的回答：</span>
          {answerSummary(options, questionAnswer) || "(空)"}
        </div>
      )}

      {/* Pending state — interactive controls */}
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
}
