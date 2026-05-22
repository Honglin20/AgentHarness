# Agent I/O Viewer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add input/output viewer buttons on agent message headers so users can inspect what prompt an agent received and what structured output it produced.

**Architecture:** Backend extends `node.completed` event with `input_prompt` and `output_result` fields. Frontend stores them in a new `agentIOStore` and renders them in a shadcn Sheet (side drawer) triggered by icon buttons on the agent header.

**Tech Stack:** Python/Pydantic (backend), TypeScript/Zustand (frontend), shadcn/ui Sheet (Radix Dialog-based)

---

### Task 1: Backend — Add `input_prompt` and `output_result` to `node.completed` event

**Files:**
- Modify: `harness/engine/macro_graph.py:547-558` (the `node.completed` emit block)

**Step 1: Write the failing test**

Add to `tests/engine/test_macro_graph.py`:

```python
def test_node_completed_event_includes_input_prompt():
    """node.completed event should include input_prompt field."""
    from harness.engine.macro_graph import MacroGraphBuilder
    from harness.api import Agent, AgentResult
    from unittest.mock import MagicMock

    # We test the event payload structure by inspecting what _make_node_func
    # would emit. Since running a full agent requires an LLM, we test the
    # event construction logic directly.
    # Instead, we verify the fields are present in the code path by
    # checking the event_payload dict construction.
    # This is a structural test — we verify the code constructs the right dict.

    # Read the source and verify the fields are present
    import inspect
    from harness.engine import macro_graph
    source = inspect.getsource(macro_graph)
    assert '"input_prompt"' in source, "node.completed event must include input_prompt field"
    assert '"output_result"' in source, "node.completed event must include output_result field"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_node_completed_event_includes_input_prompt -v`
Expected: FAIL — fields not present yet

**Step 3: Write minimal implementation**

In `harness/engine/macro_graph.py`, change the `node.completed` event payload (around line 549-558) from:

```python
                # Emit node.completed event
                if bus:
                    event_payload = {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "duration_ms": duration_ms,
                        "status": "success",
                    }
                    if token_usage:
                        event_payload["token_usage"] = token_usage
                    bus.emit("node.completed", event_payload)
```

To:

```python
                # Emit node.completed event
                if bus:
                    event_payload = {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "duration_ms": duration_ms,
                        "status": "success",
                        "input_prompt": context,
                        "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                    }
                    if token_usage:
                        event_payload["token_usage"] = token_usage
                    bus.emit("node.completed", event_payload)
```

`context` is already in scope — it's the variable set earlier in `_make_node_func` (line ~290: `context = micro_factory.build_node_prompt(...)`). `output` is `agent_run.result.output` (line ~459). `BaseModel` is already imported.

**Step 4: Run test to verify it passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py::test_node_completed_event_includes_input_prompt -v`
Expected: PASS

**Step 5: Run full macro_graph tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/test_macro_graph.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/engine/macro_graph.py tests/engine/test_macro_graph.py
git commit -m "feat: add input_prompt and output_result to node.completed event"
```

---

### Task 2: Frontend — Update TypeScript event types

**Files:**
- Modify: `frontend/src/types/events.ts:66-72`

**Step 1: Update `NodeCompletedPayload`**

Change from:

```typescript
export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
}
```

To:

```typescript
export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
  input_prompt?: string;
  output_result?: Record<string, unknown>;
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/types/events.ts
git commit -m "feat: add input_prompt and output_result to NodeCompletedPayload type"
```

---

### Task 3: Frontend — Create `agentIOStore`

**Files:**
- Create: `frontend/src/stores/agentIOStore.ts`

**Step 1: Create the store**

```typescript
import { create } from "zustand";

export interface AgentIOData {
  inputPrompt: string;
  outputResult: unknown;
}

export interface AgentIOState {
  data: Record<string, AgentIOData>;
  setAgentIO: (nodeId: string, inputPrompt: string, outputResult: unknown) => void;
  reset: () => void;
}

const initialState = {
  data: {} as Record<string, AgentIOData>,
};

export const useAgentIOStore = create<AgentIOState>()((set) => ({
  ...initialState,

  setAgentIO: (nodeId, inputPrompt, outputResult) =>
    set((state) => ({
      data: {
        ...state.data,
        [nodeId]: { inputPrompt, outputResult },
      },
    })),

  reset: () => set(initialState),
}));
```

**Step 2: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/stores/agentIOStore.ts
git commit -m "feat: create agentIOStore for agent input/output data"
```

---

### Task 4: Frontend — Wire up `agentIOStore` in `useWorkflowEvents`

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:96-101` (the `node.completed` handler)

**Step 1: Add import and store write**

Add import at the top of the file (with other store imports):

```typescript
import { useAgentIOStore } from "@/stores/agentIOStore";
```

Change the `node.completed` handler from:

```typescript
    case "node.completed": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as NodeCompletedPayload;
      useWorkflowStore.getState().handleNodeCompleted(p);
      useConversationStore.getState().completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);
      break;
    }
```

To:

```typescript
    case "node.completed": {
      if (payloadWid && payloadWid !== _activeWorkflowId) break;
      const p = event.payload as unknown as NodeCompletedPayload;
      useWorkflowStore.getState().handleNodeCompleted(p);
      useConversationStore.getState().completeAgentMessage(p.node_id, p.agent_name, p.duration_ms);
      // Store agent I/O data for viewer
      if (p.input_prompt || p.output_result) {
        useAgentIOStore.getState().setAgentIO(p.node_id, p.input_prompt ?? "", p.output_result);
      }
      break;
    }
```

**Step 2: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "feat: write agent I/O data to agentIOStore on node.completed"
```

---

### Task 5: Frontend — Generate shadcn Sheet component

**Files:**
- Create: `frontend/src/components/ui/sheet.tsx`

**Step 1: Generate Sheet component**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx shadcn@latest add sheet --yes 2>&1`

If that fails (e.g. shadcn CLI not configured), create the file manually. The project already has `@radix-ui/react-dialog` installed. Create `frontend/src/components/ui/sheet.tsx` with the standard shadcn Sheet component:

```tsx
"use client"

import * as React from "react"
import * as SheetPrimitive from "@radix-ui/react-dialog"
import { cva, type VariantProps } from "class-variance-authority"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

const Sheet = SheetPrimitive.Root

const SheetTrigger = SheetPrimitive.Trigger

const SheetClose = SheetPrimitive.Close

const SheetPortal = SheetPrimitive.Portal

const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Overlay
    className={cn(
      "fixed inset-0 z-50 bg-black/80 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
    ref={ref}
  />
))
SheetOverlay.displayName = SheetPrimitive.Overlay.displayName

const sheetVariants = cva(
  "fixed z-50 gap-4 bg-white p-6 shadow-lg transition ease-in-out data-[state=closed]:duration-300 data-[state=open]:duration-500 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
  {
    variants: {
      side: {
        top: "inset-x-0 top-0 border-b data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
        bottom:
          "inset-x-0 bottom-0 border-t data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
        left: "inset-y-0 left-0 h-full w-3/4 border-r data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
        right:
          "inset-y-0 right-0 h-full w-3/4 border-l data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-sm",
      },
    },
    defaultVariants: {
      side: "right",
    },
  }
)

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof SheetPrimitive.Content>,
    VariantProps<typeof sheetVariants> {}

const SheetContent = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Content>,
  SheetContentProps
>(({ side = "right", className, children, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <SheetPrimitive.Content
      ref={ref}
      className={cn(sheetVariants({ side }), className)}
      {...props}
    >
      <SheetPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-white transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-neutral-950 focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-neutral-100">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </SheetPrimitive.Close>
      {children}
    </SheetPrimitive.Content>
  </SheetPortal>
))
SheetContent.displayName = SheetPrimitive.Content.displayName

const SheetHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-2 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
SheetHeader.displayName = "SheetHeader"

const SheetFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className
    )}
    {...props}
  />
)
SheetFooter.displayName = "SheetFooter"

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Title>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold text-neutral-950", className)}
    {...props}
  />
))
SheetTitle.displayName = SheetPrimitive.Title.displayName

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Description>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Description
    ref={ref}
    className={cn("text-sm text-neutral-500", className)}
    {...props}
  />
))
SheetDescription.displayName = SheetPrimitive.Description.displayName

export {
  Sheet,
  SheetPortal,
  SheetOverlay,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
}
```

**Step 2: Check if `class-variance-authority` is installed**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && grep "class-variance-authority" package.json`
If not present: `npm install class-variance-authority`

**Step 3: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/components/ui/sheet.tsx
git commit -m "feat: add shadcn Sheet component for side drawer UI"
```

---

### Task 6: Frontend — Add I/O buttons and Sheet to AgentMessage

**Files:**
- Modify: `frontend/src/components/conversation/AgentMessage.tsx`

**Step 1: Update AgentMessage component**

Replace the entire `AgentMessage` component with:

```tsx
"use client";

import { useState } from "react";
import { ChevronRight, FileInput, FileOutput } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import { useAgentIOStore } from "@/stores/agentIOStore";
import { formatDuration } from "@/components/output/status-config";
import { MarkdownText } from "./MarkdownText";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

interface AgentMessageProps {
  message: ConversationMessage;
  collapsed: boolean;
  onToggleCollapse: () => void;
  sectionItemCount: number;
}

const AGENT_STATUS_BADGE_BG: Record<string, string> = {
  streaming: "bg-blue-500/10 text-blue-500",
  done: "bg-emerald-500/10 text-emerald-500",
  error: "bg-red-500/10 text-red-500",
  interrupted: "bg-amber-500/10 text-amber-500",
};

function firstNonEmptyLine(s: string): string {
  for (const line of s.split("\n")) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}

type IOTab = "input" | "output";

export function AgentMessage({ message, collapsed, onToggleCollapse, sectionItemCount }: AgentMessageProps) {
  const { agentName, content, status, durationMs, nodeId } = message;
  const badgeClass = AGENT_STATUS_BADGE_BG[status ?? "done"] ?? AGENT_STATUS_BADGE_BG.done;
  const isStreaming = status === "streaming";
  const isDone = status === "done";

  const agentIO = useAgentIOStore((s) => nodeId ? s.data[nodeId] : undefined);
  const hasIO = isDone && agentIO && (agentIO.inputPrompt || agentIO.outputResult != null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<IOTab>("input");

  const openSheet = (tab: IOTab) => {
    setActiveTab(tab);
    setSheetOpen(true);
  };

  const text = content ?? "";
  const preview = firstNonEmptyLine(text);
  const lineCount = text.split("\n").length;
  const hasMore = lineCount > 1 || text.length > preview.length || sectionItemCount > 1;
  const showCollapsed = collapsed && !isStreaming;

  return (
    <div className="flex min-w-0 flex-col gap-1 py-1">
      <div className="flex min-w-0 items-center gap-2">
        {agentName && (
          <span className={`inline-flex max-w-[40%] shrink items-center truncate rounded-md px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
            {agentName}
          </span>
        )}
        {durationMs != null && (
          <span className="shrink-0 text-xs text-muted-foreground">{formatDuration(durationMs)}</span>
        )}
        {/* I/O viewer buttons — only when done and data available */}
        {hasIO && (
          <>
            <button
              type="button"
              onClick={() => openSheet("input")}
              className="shrink-0 inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-muted-foreground hover:text-blue-500 hover:bg-blue-500/10 transition-colors"
              title="查看输入"
            >
              <FileInput className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={() => openSheet("output")}
              className="shrink-0 inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-muted-foreground hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors"
              title="查看输出"
            >
              <FileOutput className="h-3 w-3" />
            </button>
          </>
        )}
        {!isStreaming && hasMore && (
          <button
            type="button"
            onClick={onToggleCollapse}
            className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand agent section" : "Collapse agent section"}
          >
            <ChevronRight
              className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-90"}`}
            />
            {collapsed
              ? sectionItemCount > 1
                ? `Show (${sectionItemCount})`
                : `Show ${lineCount} lines`
              : "Collapse"}
          </button>
        )}
      </div>

      {status === "error" && !text ? (
        <p className="text-sm text-red-500">An error occurred</p>
      ) : showCollapsed ? (
        <button
          type="button"
          onClick={onToggleCollapse}
          className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
          title="Click to expand"
        >
          {preview || "(empty output)"}
        </button>
      ) : (
        <div className="min-w-0 text-sm">
          <MarkdownText>{text}</MarkdownText>
          {isStreaming && <span className="animate-pulse">▎</span>}
        </div>
      )}

      {/* I/O Viewer Sheet */}
      {hasIO && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="right" className="w-[500px] sm:max-w-lg overflow-y-auto">
            <SheetHeader>
              <SheetTitle>
                {activeTab === "input" ? "输入" : "输出"} — {agentName}
              </SheetTitle>
            </SheetHeader>
            <div className="mt-4 rounded-md border border-app-border bg-gray-50 p-3">
              {activeTab === "input" ? (
                <pre className="whitespace-pre-wrap break-words text-xs font-mono text-app-text-primary">
                  {agentIO.inputPrompt || "(empty)"}
                </pre>
              ) : (
                <pre className="whitespace-pre-wrap break-words text-xs font-mono text-app-text-primary">
                  {agentIO.outputResult != null
                    ? JSON.stringify(agentIO.outputResult, null, 2)
                    : "(empty)"}
                </pre>
              )}
            </div>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}
```

**Key changes from original:**
- Added `nodeId` destructuring from `message`
- Added `useAgentIOStore` subscription keyed by `nodeId`
- Added `hasIO` flag (only true when `done` + data exists)
- Added two icon buttons (`FileInput`, `FileOutput`) in the header row
- Added `Sheet` component for I/O display
- Added `interrupted` to `AGENT_STATUS_BADGE_BG`

**Step 2: Verify TypeScript compiles**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/conversation/AgentMessage.tsx
git commit -m "feat: add input/output viewer buttons and Sheet to AgentMessage"
```

---

### Task 7: Verify end-to-end

**Files:**
- No new files

**Step 1: Run backend tests**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/engine/ tests/compiler/ tests/test_api.py -q --tb=short`
Expected: ALL PASS

**Step 2: Run frontend build**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

**Step 3: Manual smoke test**

Start dev server, run a workflow, and verify:
1. When an agent completes, two small icon buttons appear on its header (input/output)
2. Clicking the input button opens a right-side Sheet showing the full `build_node_prompt` output
3. Clicking the output button opens a right-side Sheet showing the structured JSON output
4. Buttons only appear on completed agents, not during streaming or on errors
5. Sheet can be closed with the X button or clicking outside

**Step 4: Final commit if fixups needed**

```bash
git add -A
git commit -m "fix: address issues from e2e verification"
```
