# UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the three-column layout with a two-column conversational UI — DAG status bar on top, chat-style message stream in center, Results tab for charts, Diagnostics on right.

**Architecture:** Bottom-up: stores first (data model), then components (presentation), then layout (assembly). Each task is independently testable. Old components are deleted only after new ones fully replace them.

**Tech Stack:** React 18, Zustand, dagre (SVG layout), recharts (existing), @xyflow/react removed from DAG rendering, react-resizable-panels

---

### Task 1: Create conversation store

**Files:**
- Create: `frontend/src/stores/conversationStore.ts`

**Step 1: Write the conversation store**

```ts
import { create } from "zustand";

export interface ConversationMessage {
  id: string;
  type: "agent" | "user" | "tool_call" | "system";
  nodeId?: string;
  agentName?: string;
  content: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  status?: "streaming" | "done" | "error";
  durationMs?: number;
  timestamp: number;
}

export interface ConversationState {
  messages: ConversationMessage[];
  pendingQuestionId: string | null;
  pendingQuestionAgent: string | null;

  // Actions
  addSystemMessage: (content: string) => void;
  addAgentMessage: (nodeId: string, agentName: string) => void;
  appendAgentText: (nodeId: string, text: string) => void;
  completeAgentMessage: (nodeId: string, agentName: string, durationMs?: number) => void;
  failAgentMessage: (nodeId: string, agentName: string, error: string, durationMs?: number) => void;
  addToolCall: (nodeId: string, agentName: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  addToolResult: (nodeId: string, toolName: string, result: string) => void;
  addAgentQuestion: (questionId: string, question: string, agentName: string) => void;
  addUserMessage: (content: string) => void;
  clearPendingQuestion: (questionId: string) => void;
  reset: () => void;
}

let _nextId = 0;
function nextId(): string {
  return `msg-${++_nextId}`;
}

const initialState = {
  messages: [] as ConversationMessage[],
  pendingQuestionId: null as string | null,
  pendingQuestionAgent: null as string | null,
};

export const useConversationStore = create<ConversationState>()((set) => ({
  ...initialState,

  addSystemMessage: (content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: nextId(), type: "system", content, timestamp: Date.now() },
      ],
    })),

  addAgentMessage: (nodeId, agentName) =>
    set((state) => {
      // If there's already a streaming message for this node, don't add another
      const existing = state.messages.find(
        (m) => m.nodeId === nodeId && m.status === "streaming"
      );
      if (existing) return state;
      return {
        messages: [
          ...state.messages,
          {
            id: nextId(),
            type: "agent",
            nodeId,
            agentName,
            content: "",
            status: "streaming",
            timestamp: Date.now(),
          },
        ],
      };
    }),

  appendAgentText: (nodeId, text) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
      );
      if (idx === -1) return state;
      const updated = [...state.messages];
      updated[idx] = { ...updated[idx], content: updated[idx].content + text };
      return { messages: updated };
    }),

  completeAgentMessage: (nodeId, agentName, durationMs) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
      );
      if (idx === -1) return state;
      const updated = [...state.messages];
      updated[idx] = { ...updated[idx], status: "done", durationMs };
      return { messages: updated };
    }),

  failAgentMessage: (nodeId, agentName, error, durationMs) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
      );
      if (idx === -1) return state;
      const updated = [...state.messages];
      updated[idx] = { ...updated[idx], status: "error", content: updated[idx].content || error, durationMs };
      return { messages: updated };
    }),

  addToolCall: (nodeId, agentName, toolName, toolArgs) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: nextId(),
          type: "tool_call",
          nodeId,
          agentName,
          content: "",
          toolName,
          toolArgs,
          timestamp: Date.now(),
        },
      ],
    })),

  addToolResult: (nodeId, toolName, result) =>
    set((state) => {
      // Find the most recent tool_call for this node+tool without a result
      const idx = state.messages.findLastIndex(
        (m) =>
          m.type === "tool_call" &&
          m.nodeId === nodeId &&
          m.toolName === toolName &&
          m.toolResult === undefined
      );
      if (idx === -1) return state;
      const updated = [...state.messages];
      updated[idx] = { ...updated[idx], toolResult: result };
      return { messages: updated };
    }),

  addAgentQuestion: (questionId, question, agentName) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: nextId(),
          type: "agent",
          nodeId: agentName,
          agentName,
          content: question,
          status: "done" as const,
          timestamp: Date.now(),
        },
      ],
      pendingQuestionId: questionId,
      pendingQuestionAgent: agentName,
    })),

  addUserMessage: (content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: nextId(),
          type: "user",
          content,
          timestamp: Date.now(),
        },
      ],
    })),

  clearPendingQuestion: (questionId) =>
    set((state) =>
      state.pendingQuestionId === questionId
        ? { pendingQuestionId: null, pendingQuestionAgent: null }
        : state
    ),

  reset: () => {
    _nextId = 0;
    set(initialState);
  },
}));
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit src/stores/conversationStore.ts 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/stores/conversationStore.ts
git commit -m "feat: add conversation store for chat-style message stream"
```

---

### Task 2: Wire conversation store into event dispatcher

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts`

**Step 1: Update useWorkflowEvents to populate conversation store**

Replace the existing event handlers with ones that also write to `useConversationStore`. Key changes:
- `workflow.started` → `addSystemMessage`
- `node.started` → `addAgentMessage`
- `agent.text_delta` → `appendAgentText` (instead of `outputStore.appendText`)
- `node.completed` → `completeAgentMessage`
- `node.failed` → `failAgentMessage`
- `agent.tool_call` → `addToolCall` (in addition to existing toolCallStore)
- `agent.tool_result` → `addToolResult` (in addition to existing toolCallStore)
- `chat.question` → `addAgentQuestion`
- `chat.answer` → `addUserMessage` + `clearPendingQuestion`
- `workflow.resumed` → `addSystemMessage`

Keep the existing `workflowStore`, `outputStore`, `chatStore`, `toolCallStore` writes in place for backward compatibility during the transition. They will be removed once old components are deleted.

**Step 2: Verify it compiles**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "feat: wire conversation store into event dispatcher"
```

---

### Task 3: Create DAGStatusBar component

**Files:**
- Create: `frontend/src/components/dag/DAGStatusBar.tsx`

**Step 1: Implement DAGStatusBar with dagre + SVG**

A horizontal bar (~48px) that renders the DAG using dagre LR layout and custom SVG. Uses `workflowStore.dag` and `workflowStore.nodes` as data sources.

Key implementation:
- Use `dagre` with `rankdir: "LR"` to compute node positions
- Render SVG: circles for nodes, lines/paths for edges
- Node colors by status (idle/running/success/failed)
- Conditional edges: dashed lines with colored labels
- Loop edges: curved arc path (SVG quadratic bezier)
- Horizontally scrollable container
- Click handler: sets `selectedNodeId` in workflowStore (for Diagnostics highlight)

**Step 2: Verify it renders in isolation**

Temporarily add `<DAGStatusBar />` to page.tsx alongside existing layout. Run `cd frontend && npx next build` and check browser.

**Step 3: Commit**

```bash
git add frontend/src/components/dag/DAGStatusBar.tsx
git commit -m "feat: add DAGStatusBar — compact SVG-based DAG visualization"
```

---

### Task 4: Create ConversationTab component

**Files:**
- Create: `frontend/src/components/conversation/ConversationTab.tsx`
- Create: `frontend/src/components/conversation/AgentMessage.tsx`
- Create: `frontend/src/components/conversation/UserMessage.tsx`
- Create: `frontend/src/components/conversation/SystemMessage.tsx`
- Create: `frontend/src/components/conversation/ToolCallMessage.tsx`

**Step 1: Implement message sub-components**

Each renders one message type from the conversation store:

- **AgentMessage**: left-aligned, agent name badge with status color, streaming markdown body (reuse `react-markdown` if already in deps, otherwise simple `<pre>` with whitespace pre-wrap), duration badge when done
- **UserMessage**: right-aligned blue bubble, just the text content
- **SystemMessage**: centered gray text with separator lines
- **ToolCallMessage**: indented collapsible card. Shows tool name + args preview. Expandable to show toolResult. Use the existing `Collapsible` shadcn component.

**Step 2: Implement ConversationTab**

Scrolls through `conversationStore.messages`, renders appropriate sub-component per message type. Auto-scrolls to bottom on new messages.

**Step 3: Verify it compiles**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add frontend/src/components/conversation/
git commit -m "feat: add ConversationTab with agent/user/system/tool message types"
```

---

### Task 5: Create ResultsTab component

**Files:**
- Create: `frontend/src/components/results/ResultsTab.tsx`

**Step 1: Implement ResultsTab**

Reuses the existing `chartStore` (which already has grouping by label, de-duplication by label+title, and collapse toggle). Renders each group as a collapsible card with full-width chart widgets.

Reuse existing chart widget components from `frontend/src/components/output/charts/` and `ChartWidget.tsx`. The key difference: render them at full width/height instead of cramped in 20% panel height.

Empty state: centered text "No results yet. Results will appear here when agents produce charts or tables."

**Step 2: Verify it compiles**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/components/results/ResultsTab.tsx
git commit -m "feat: add ResultsTab — full-width chart/table display grouped by label"
```

---

### Task 6: Rewrite CenterPanel with tab layout + shared input

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx`

**Step 1: Rewrite CenterPanel**

Replace the current three-panel vertical layout (AgentStatusBar + StreamingText / ChartBar / Chat) with:
- Tab bar at top: `[Conversation]  [Results ·N]` where N is number of chart groups from chartStore
- Tab content area: either ConversationTab or ResultsTab
- Shared input box at bottom: `ChatInput` component with placeholder that changes based on `pendingQuestionId`

The Results tab badge animates when a new chart arrives while on the Conversation tab.

**Step 2: Verify it compiles and renders**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/components/layout/CenterPanel.tsx
git commit -m "feat: rewrite CenterPanel with Conversation/Results tabs + shared input"
```

---

### Task 7: Update page.tsx — remove left column, add DAGStatusBar

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Rewrite page.tsx**

Replace the three-column layout with:
```
HeaderBar
DAGStatusBar (visible when workflow is active)
Two-column: CenterPanel (~78%) | DiagnosticsPanel (~22%)
```

Remove: `DAGPanel` import and its `<Panel>` entry.
Add: `DAGStatusBar` import, rendered between HeaderBar and the panel group.
Adjust: Panel proportions (78%/22%).

**Step 2: Verify full page renders**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: replace three-column layout with two-column + DAG status bar"
```

---

### Task 8: Update ChatInput for contextual placeholder

**Files:**
- Modify: `frontend/src/components/chat/ChatInput.tsx`

**Step 1: Add contextual placeholder**

When `conversationStore.pendingQuestionId` is set, change placeholder to `"回答 {agentName} 的问题..."`. When sending a message:
- If pending question exists → call `sendAnswer(questionId, input)` + `addUserMessage(input)` + `clearPendingQuestion(questionId)`
- Otherwise → call `sendInterrupt(input)` or `addUserMessage(input)` (for conversational input)

Also add an Enter key handler that calls the appropriate send action.

**Step 2: Verify it works**

Manual test: run a workflow with ask_human, verify placeholder changes and answer routes correctly.

**Step 3: Commit**

```bash
git add frontend/src/components/chat/ChatInput.tsx
git commit -m "feat: contextual input placeholder for ask_human + unified send logic"
```

---

### Task 9: Wire DAG node click → Diagnostics highlight

**Files:**
- Modify: `frontend/src/stores/workflowStore.ts` — add `selectedNodeId` state
- Modify: `frontend/src/components/dag/DAGStatusBar.tsx` — add click handler
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx` — read selectedNodeId, auto-switch tab

**Step 1: Add selectedNodeId to workflowStore**

```ts
selectedNodeId: string | null;
setSelectedNode: (id: string | null) => void;
```

**Step 2: Add click handler in DAGStatusBar**

On node circle click → `workflowStore.setSelectedNode(nodeId)`

**Step 3: Auto-switch Diagnostics tab**

When `selectedNodeId` changes and is non-null, switch Diagnostics active tab to "trace" and scroll to the corresponding entry.

**Step 4: Commit**

```bash
git add frontend/src/stores/workflowStore.ts frontend/src/components/dag/DAGStatusBar.tsx frontend/src/components/diagnostics/DiagnosticsPanel.tsx
git commit -m "feat: DAG node click → Diagnostics highlight"
```

---

### Task 10: Delete old components and unused stores

**Files:**
- Delete: `frontend/src/components/layout/DAGPanel.tsx`
- Delete: `frontend/src/components/dag/DAGCanvas.tsx`
- Delete: `frontend/src/components/dag/AgentNode.tsx`
- Delete: `frontend/src/components/output/AgentStatusBar.tsx`
- Delete: `frontend/src/components/output/ChartBar.tsx`
- Delete: `frontend/src/components/output/StreamingText.tsx`
- Delete: `frontend/src/components/chat/MessageList.tsx`
- Delete: `frontend/src/lib/dagLayout.ts` (replaced by inline dagre in DAGStatusBar)
- Clean up: remove `outputStore` references from `useWorkflowEvents.ts` (now using conversationStore)
- Clean up: remove `chatStore` references from `useWorkflowEvents.ts` (now using conversationStore)

**Step 1: Delete unused files**

**Step 2: Clean up imports and references**

Search for any remaining imports of deleted components and remove them.

**Step 3: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -10`
Expected: Build succeeds with no errors

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete old DAG panel, AgentStatusBar, ChartBar, StreamingText, MessageList"
```

---

### Task 11: Visual polish and edge cases

**Files:**
- Modify: various components as needed

**Step 1: Polish the following**

- DAGStatusBar: ensure loop edges render correctly as curved arcs
- ConversationTab: smooth auto-scroll, markdown rendering
- ResultsTab: responsive grid for multiple charts, proper empty state
- CenterPanel: tab transition animation
- Overall: verify all states (idle, running, completed, failed, cancelled) look correct

**Step 2: Full manual test**

1. Start a workflow → verify DAGStatusBar shows nodes, Conversation shows messages
2. Ask human question → verify placeholder changes, answer appears as user message
3. Chart rendering → verify Results tab shows charts at full width, grouped by label
4. Cancel workflow → verify Stop button works, state resets
5. Error case → verify failed node shows in red in DAGStatusBar and error message in conversation

**Step 3: Commit**

```bash
git add -A
git commit -m "fix: polish UI — loop edges, markdown, tab transitions, edge cases"
```

---

### Task 12: Update design doc and spec

**Files:**
- Modify: `docs/plans/2026-05-21-ui-redesign-design.md`
- Modify: `SPEC.md` — update frontend component sections if they exist

**Step 1: Mark completed items in design doc**

**Step 2: Update SPEC.md with new component interfaces**

**Step 3: Commit**

```bash
git add docs/plans/ SPEC.md
git commit -m "docs: update design doc and spec after UI redesign implementation"
```

---

## Task Dependency Graph

```
Task 1 (conversation store)
  └→ Task 2 (wire events)
       └→ Task 4 (ConversationTab)
            └→ Task 6 (CenterPanel rewrite)

Task 3 (DAGStatusBar)
  └→ Task 7 (page.tsx)
  └→ Task 9 (DAG click → Diagnostics)

Task 5 (ResultsTab)
  └→ Task 6 (CenterPanel rewrite)

Task 6 + Task 7 → Task 8 (ChatInput)
Task 8 → Task 10 (cleanup)
Task 10 → Task 11 (polish)
Task 11 → Task 12 (docs)
```

Tasks 1, 3, 5 can start in parallel (no dependencies on each other).
