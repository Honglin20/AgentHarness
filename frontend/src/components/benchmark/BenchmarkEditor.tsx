"use client";

import { useState, useCallback } from "react";
import { Save, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Task {
  label: string;
  inputs: Record<string, string>;
}

interface Props {
  onSave: (name: string, tasks: Task[], description: string) => void;
  initialName?: string;
  initialTasks?: Task[];
  initialDescription?: string;
}

export default function BenchmarkEditor({
  onSave,
  initialName = "",
  initialTasks = [{ label: "", inputs: {} }],
  initialDescription = "",
}: Props) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [tasks, setTasks] = useState<Task[]>(initialTasks);
  const [saving, setSaving] = useState(false);

  const addTask = useCallback(() => {
    setTasks((prev) => [...prev, { label: "", inputs: {} }]);
  }, []);

  const removeTask = useCallback((index: number) => {
    setTasks((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateTask = useCallback((index: number, label: string) => {
    setTasks((prev) => {
      const next = [...prev];
      next[index] = { label, inputs: { task: label } };
      return next;
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!name.trim() || tasks.every((t) => !t.label.trim())) return;
    setSaving(true);
    try {
      await onSave(
        name.trim(),
        tasks.filter((t) => t.label.trim()),
        description.trim(),
      );
    } finally {
      setSaving(false);
    }
  }, [name, tasks, description, onSave]);

  const validTasks = tasks.filter((t) => t.label.trim()).length;

  return (
    <div className="flex flex-col gap-4 p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
        New Benchmark
      </h3>

      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Benchmark name"
        className="h-9 text-sm"
      />

      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        className="h-9 text-sm"
      />

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-app-text-secondary">
            Tasks ({validTasks})
          </h4>
          <Button variant="ghost" size="sm" onClick={addTask} className="h-7 text-xs">
            <Plus className="mr-1 h-3 w-3" /> Add Task
          </Button>
        </div>

        {tasks.map((task, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-6 text-right text-xs text-muted-foreground">{i + 1}</span>
            <Input
              value={task.label}
              onChange={(e) => updateTask(i, e.target.value)}
              placeholder={`Task ${i + 1} description`}
              className="h-8 text-sm"
            />
            {tasks.length > 1 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeTask(i)}
                className="h-8 w-8 p-0 text-muted-foreground hover:text-red-500"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        ))}
      </div>

      <Button
        onClick={handleSave}
        disabled={!name.trim() || validTasks === 0 || saving}
        className="h-9 w-full text-sm"
      >
        {saving ? (
          "Saving..."
        ) : (
          <>
            <Save className="mr-2 h-3.5 w-3.5" />
            Save Benchmark
          </>
        )}
      </Button>
    </div>
  );
}
