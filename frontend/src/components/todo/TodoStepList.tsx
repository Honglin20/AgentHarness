"use client";

import { useStore } from "zustand";
import type { StoreApi } from "zustand/vanilla";
import type { TodoState, TodoStep } from "@/contexts/workflow-context/workflowStores";

interface TodoStepListProps {
  nodeId: string;
  todoStore: StoreApi<TodoState>;
}

const STATUS_ICONS: Record<TodoStep["status"], { symbol: string; className: string }> = {
  pending: { symbol: "⬜", className: "text-gray-400" },
  in_progress: { symbol: "🔵", className: "text-blue-500 todo-pulse" },
  completed: { symbol: "✅", className: "text-green-500" },
  interrupted: { symbol: "⏸", className: "text-amber-500" },
};

export default function TodoStepList({ nodeId, todoStore }: TodoStepListProps) {
  const todos = useStore(todoStore, (s) => s.todos[nodeId]);

  if (!todos || todos.length === 0) return null;

  return (
    <div className="todo-step-list rounded-lg border border-zinc-700/50 bg-zinc-800/50 p-3 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Steps</span>
        <span className="text-xs text-zinc-500">
          {todos.filter((s) => s.status === "completed").length}/{todos.length}
        </span>
      </div>
      <ul className="space-y-1.5">
        {todos.map((step) => (
          <TodoStepItem key={step.taskId} step={step} />
        ))}
      </ul>
    </div>
  );
}

function TodoStepItem({ step }: { step: TodoStep }) {
  const { symbol, className } = STATUS_ICONS[step.status] ?? STATUS_ICONS.pending;
  const isActive = step.status === "in_progress";
  const isDone = step.status === "completed";

  return (
    <li className="flex flex-col">
      <div className="flex items-center gap-2">
        <span className={`text-sm ${isActive ? "todo-pulse" : ""}`}>{symbol}</span>
        <span
          className={`text-sm ${
            isDone
              ? "text-zinc-500 line-through"
              : isActive
              ? "text-zinc-200 font-medium"
              : "text-zinc-400"
          }`}
        >
          {isActive ? step.activeForm : step.content}
        </span>
      </div>
      {step.detail && (
        <div className="ml-6 mt-0.5 text-xs text-zinc-500 truncate" title={step.detail ?? undefined}>{step.detail}</div>
      )}
    </li>
  );
}
