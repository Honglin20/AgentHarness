# Fix Context Architecture Critical Defects

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 critical defects that break ChatInput, AgentMessage, and getMessageCounter under Context architecture.

**Architecture:** The approach is **props injection** — ChatInput and AgentMessage receive store selectors as optional props. When used inside Context architecture (ScopedCenterPanel), the parent passes scoped store selectors. When used inside Legacy (CenterPanel), the parent passes nothing and the components fall back to their current global store reads. This avoids creating duplicate Scoped* components.

**Tech Stack:** React props, Zustand stores, TypeScript

---

## Defects Fixed

| # | Defect | Root Cause | Fix |
|---|--------|-----------|-----|
| K1 | ChatInput reads from legacy global store | No scoped store injection | Add optional store selector props |
| K2 | AgentMessage reads agentIO/nodes from global store | No scoped store injection | Add optional store selector props |
| K3 | `getMessageCounter` returns undefined for scoped stores | Missing `_msgCounter` attachment | Add the missing line |

---

### Task 1: Fix `getMessageCounter` — attach `_msgCounter` to scoped store

**Files:**
- Modify: `frontend/src/contexts/workflow-context/workflowStores.ts`

**Step 1: Find the missing attachment line**

In `createToolCallStore` (~line 1016), the working pattern is:
```typescript
(store as unknown as { _tcCounter: ToolCallCounter })._tcCounter = tcCounter;
```

In `createConversationStore`, `msgCounter` is created at ~line 73 but never attached.

**Step 2: Add the missing line**

Find the `return store;` line at the end of `createConversationStore` (around line 512-513). Add the attachment line BEFORE `return store;`:

```typescript
(store as unknown as { _msgCounter: MessageCounter })._msgCounter = msgCounter;
return store;
```

**Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -i workflowStores`

Expected: No errors related to workflowStores.

**Step 4: Commit**

```
fix: attach _msgCounter to scoped conversation store
```

---

### Task 2: Fix `AgentMessage` — accept scoped store selectors via props

**Files:**
- Modify: `frontend/src/components/conversation/AgentMessage.tsx`

**Why props injection:** `AgentMessage` is rendered by BOTH `ScopedConversationTab` and legacy `ConversationTab`. Creating a `ScopedAgentMessage` would duplicate the entire component. Instead, add optional props that override the global store reads.

**Step 1: Add optional store selector props**

Add to the `AgentMessageProps` interface:

```typescript
interface AgentMessageProps {
  message: ConversationMessage;
  collapsed: boolean;
  onToggleCollapse: () => void;
  sectionItemCount: number;
  // Optional scoped store selectors — override global store reads when provided
  getAgentIO?: (nodeId: string) => { inputPrompt?: string; outputResult?: unknown; systemPrompt?: string } | undefined;
  getNodeState?: (nodeId: string) => { tokenUsage?: number; tools?: ToolBrief[] } | undefined;
}
```

**Step 2: Use props with fallback to global store**

Replace lines 132-136:

```typescript
// OLD:
const agentIO = useAgentIOStore((s) => nodeId ? s.data[nodeId] : undefined);
const nodeState = useWorkflowStore((s) => nodeId ? s.nodes[nodeId] : undefined);

// NEW:
const globalAgentIO = useAgentIOStore((s) => nodeId ? s.data[nodeId] : undefined);
const globalNodeState = useWorkflowStore((s) => nodeId ? s.nodes[nodeId] : undefined);
const agentIO = getAgentIO && nodeId ? getAgentIO(nodeId) : globalAgentIO;
const nodeState = getNodeState && nodeId ? getNodeState(nodeId) : globalNodeState;
```

**Step 3: Update function signature**

```typescript
export function AgentMessage({
  message,
  collapsed,
  onToggleCollapse,
  sectionItemCount,
  getAgentIO,
  getNodeState,
}: AgentMessageProps) {
```

**Step 4: Commit**

```
fix: AgentMessage accepts scoped store selectors via optional props
```

---

### Task 3: Wire `ScopedConversationTab` to pass scoped store selectors to `AgentMessage`

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx`

**Step 1: Import scoped store hooks**

Add imports:
```typescript
import { useScopedAgentIOStore, useScopedWorkflowStore } from "@/contexts/workflow-context";
```

Check that these hooks exist in `hooks.ts`. If they don't, use `useWorkflowStore("agentIO")` and `useWorkflowStore("workflow")` from the context.

**Step 2: Create selector callbacks**

Inside `ScopedConversationTab`, create the selectors:

```typescript
const agentIOStore = useWorkflowStore("agentIO");
const workflowStoreApi = useWorkflowStore("workflow");

const getAgentIO = useCallback((nodeId: string) => {
  return agentIOStore?.getState().data[nodeId];
}, [agentIOStore]);

const getNodeState = useCallback((nodeId: string) => {
  return workflowStoreApi?.getState().nodes[nodeId];
}, [workflowStoreApi]);
```

**Step 3: Pass to AgentMessage**

Update the `<AgentMessage>` render:
```tsx
<AgentMessage
  key={m.id}
  message={m}
  collapsed={isCollapsed}
  onToggleCollapse={() => toggle(m.id)}
  sectionItemCount={1}
  getAgentIO={getAgentIO}
  getNodeState={getNodeState}
/>
```

**Step 4: Commit**

```
fix: ScopedConversationTab passes scoped store selectors to AgentMessage
```

---

### Task 4: Fix `ChatInput` — accept scoped store selectors via props

**Files:**
- Modify: `frontend/src/components/chat/ChatInput.tsx`

**Step 1: Add optional store selector props**

Expand `ChatInputProps`:

```typescript
interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  startWorkflow?: (template: unknown, task: string) => void;
  alwaysVisible?: boolean;
  // Optional scoped store selectors — override global store reads when provided
  useConversationState?: () => {
    pendingQuestionId: string | null;
    pendingQuestionAgent: string | null;
    messages: ConversationMessage[];
    addUserMessage: (text: string) => void;
    clearPendingQuestion: (id: string) => void;
    interruptAgentMessage: (agentName: string) => void;
  };
  useWorkflowState?: () => {
    status: string;
    workflowId: string | null;
    selectedTemplate: unknown;
  };
}
```

**Step 2: Use props with fallback**

At the top of the component, resolve store access:

```typescript
export default function ChatInput({
  sendAnswer,
  sendStopAndRegenerate,
  startWorkflow,
  alwaysVisible = false,
  useConversationState,
  useWorkflowState,
}: ChatInputProps) {
  // Scoped store access (Context architecture) or global fallback (Legacy)
  const conv = useConversationState
    ? useConversationState()
    : {
        pendingQuestionId: useConversationStore((s) => s.pendingQuestionId),
        pendingQuestionAgent: useConversationStore((s) => s.pendingQuestionAgent),
        messages: useConversationStore((s) => s.messages),
        addUserMessage: (text: string) => useConversationStore.getState().addUserMessage(text),
        clearPendingQuestion: (id: string) => useConversationStore.getState().clearPendingQuestion(id),
        interruptAgentMessage: (name: string) => useConversationStore.getState().interruptAgentMessage(name),
      };

  const wf = useWorkflowState
    ? useWorkflowState()
    : {
        status: useWorkflowStore((s) => s.status),
        workflowId: useWorkflowStore((s) => s.workflowId),
        selectedTemplate: useWorkflowStore((s) => s.selectedTemplate),
      };

  const { pendingQuestionId, pendingQuestionAgent, messages } = conv;
  const { status, workflowId, selectedTemplate } = wf;
```

**Step 3: Replace all `useConversationStore.getState()` calls**

Replace the mutations in `handleSend`, `handleStop`, `handlePausedSubmit`:

```typescript
// handleSend:
conv.addUserMessage(trimmed);
conv.clearPendingQuestion(pendingQuestionId);

// handleStop:
conv.interruptAgentMessage(agentName);

// handlePausedSubmit:
conv.addUserMessage(guidance);
```

**Step 4: Commit**

```
fix: ChatInput accepts scoped store selectors via optional props
```

---

### Task 5: Wire `ScopedCenterPanel` to pass scoped store selectors to `ChatInput`

**Files:**
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx`

**Step 1: Create store selector hooks**

Inside `ScopedCenterPanel`, create the hooks that ChatInput expects:

```typescript
const conversationActions = useConversationActions();
const useConversationState = useCallback(() => {
  const store = useScopedConversationStore();
  const state = store?.getState();
  return {
    pendingQuestionId: state?.pendingQuestionId ?? null,
    pendingQuestionAgent: state?.pendingQuestionAgent ?? null,
    messages: state?.messages ?? [],
    addUserMessage: (text: string) => store?.getState().addUserMessage(text),
    clearPendingQuestion: (id: string) => store?.getState().clearPendingQuestion(id),
    interruptAgentMessage: (name: string) => store?.getState().interruptAgentMessage(name),
  };
}, [/* deps */]);
```

Wait — this won't work as a hook inside a hook. The correct approach is to create a **factory function** that reads from the scoped store and returns the shape ChatInput expects.

Instead, create a standalone hook in the component:

```typescript
function useScopedConversationForChatInput() {
  const store = useScopedConversationStore();
  const pendingQuestionId = useConversationStoreFromContext((s) => s.pendingQuestionId);
  // ...
}
```

Actually, the simplest correct approach: **don't use a hook prop**. Instead, pass a plain object derived from scoped stores.

Change `ChatInputProps` to accept a `storeOverrides` object:

```typescript
interface ChatInputProps {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate?: (agentName: string, partialOutput: string, userGuidance: string) => void;
  startWorkflow?: (template: unknown, task: string) => void;
  alwaysVisible?: boolean;
  conversationStore?: {
    pendingQuestionId: string | null;
    pendingQuestionAgent: string | null;
    messages: ConversationMessage[];
    addUserMessage: (text: string) => void;
    clearPendingQuestion: (id: string) => void;
    interruptAgentMessage: (name: string) => void;
  };
  workflowStore?: {
    status: string;
    workflowId: string | null;
    selectedTemplate: unknown;
  };
}
```

Then in ChatInput, use the override if provided, otherwise fall back to global stores.

This avoids the "hook inside callback" problem. The ScopedCenterPanel reads from scoped stores using existing hooks and passes the values as a plain object.

**Step 2: In ScopedCenterPanel, build the override objects**

```typescript
import { useScopedConversationStore, useScopedWorkflowStore } from "@/contexts/workflow-context";
import type { ConversationMessage } from "@/stores/conversationStore";

// Inside ScopedCenterPanel:
const scopedConvStore = useScopedConversationStore();
const scopedWfStore = useScopedWorkflowStore();

// Build ChatInput props from scoped stores
const conversationStoreOverride = scopedConvStore ? {
  get pendingQuestionId() { return scopedConvStore.getState().pendingQuestionId; },
  get pendingQuestionAgent() { return scopedConvStore.getState().pendingQuestionAgent; },
  get messages() { return scopedConvStore.getState().messages; },
  addUserMessage: (text: string) => scopedConvStore.getState().addUserMessage(text),
  clearPendingQuestion: (id: string) => scopedConvStore.getState().clearPendingQuestion(id),
  interruptAgentMessage: (name: string) => scopedConvStore.getState().interruptAgentMessage(name),
} : undefined;

const workflowStoreOverride = scopedWfStore ? {
  get status() { return scopedWfStore.getState().status; },
  get workflowId() { return scopedWfStore.getState().workflowId; },
  get selectedTemplate() { return scopedWfStore.getState().selectedTemplate; },
} : undefined;
```

Wait — using getters means ChatInput won't re-render on store changes. The ChatInput component uses React hooks (`useConversationStore(selector)`) to subscribe to changes. If we pass plain objects, there's no reactivity.

The correct approach is: **ChatInput should use the scoped hooks directly when inside Context architecture.**

**Revised approach: conditional hooks.**

ChatInput already receives `sendAnswer` and `sendStopAndRegenerate` from the parent. In Context architecture, these come from `useWSMethods()`. The issue is that ChatInput also needs to READ state (pendingQuestionId, messages, status).

The cleanest fix: **add optional reactive subscriptions as props.**

Actually, the simplest and most correct approach is:

1. ChatInput checks if it's inside a WorkflowProvider (using `useWorkflowContextSafe()`)
2. If yes, use scoped hooks
3. If no, use legacy global stores

But this violates the principle that components shouldn't know about the architecture.

**Final approach: props-based with reactive subscriptions.**

Pass React state values (not getters) as props:

In ScopedCenterPanel:
```typescript
// These are reactive because they use hooks
const pendingQuestionId = useConversationStore hook from context...
const pendingQuestionAgent = ...
const messages = ...
const status = useWorkflowStatus() // already exists
```

ScopedCenterPanel already has:
- `useConversationActions()` → `conversationActions`
- `useWorkflowStatus()` → `status`
- `useWorkflowId()` → `workflowId`

It's missing:
- `pendingQuestionId` from scoped conversation store
- `pendingQuestionAgent` from scoped conversation store
- `messages` from scoped conversation store
- `selectedTemplate` from scoped workflow store

Add these using existing context hooks, then pass as props to ChatInput.

**Step 3: Add missing hooks to ScopedCenterPanel**

```typescript
import { useConversationMessages, usePendingQuestion, useSelectedTemplate } from "@/contexts/workflow-context";

// Inside component:
const messages = useConversationMessages();
const { pendingQuestionId, pendingQuestionAgent } = usePendingQuestion();
const selectedTemplate = useSelectedTemplate();
```

Check if `usePendingQuestion` exists in hooks.ts — it does (returns `{ pendingQuestionId, pendingQuestionAgent }`).

**Step 4: Pass to ChatInput**

Add props to ChatInput:

```typescript
interface ChatInputProps {
  // ... existing props ...
  // Optional overrides for Context architecture
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
```

In ChatInput, use override if provided, otherwise read from global store:

```typescript
const pendingQuestionId = prop_pendingQuestionId ?? useConversationStore((s) => s.pendingQuestionId);
// ... etc
```

Wait, this has the React hooks conditional problem — you can't conditionally call hooks.

**Correct final approach: Always call hooks, then override the values.**

```typescript
// Always call global store hooks (React rules)
const globalPendingId = useConversationStore((s) => s.pendingQuestionId);
const globalPendingAgent = useConversationStore((s) => s.pendingQuestionAgent);
const globalMessages = useConversationStore((s) => s.messages);
const globalStatus = useWorkflowStore((s) => s.status);
const globalWid = useWorkflowStore((s) => s.workflowId);
const globalTemplate = useWorkflowStore((s) => s.selectedTemplate);

// Use props if provided (Context architecture), otherwise global (Legacy)
const pendingQuestionId = _overridePendingId !== undefined ? _overridePendingId : globalPendingId;
const pendingQuestionAgent = _overridePendingAgent !== undefined ? _overridePendingAgent : globalPendingAgent;
const messages = _overrideMessages !== undefined ? _overrideMessages : globalMessages;
const status = _overrideStatus !== undefined ? _overrideStatus : globalStatus;
const workflowId = _overrideWid !== undefined ? _overrideWid : globalWid;
const selectedTemplate = _overrideTemplate !== undefined ? _overrideTemplate : globalTemplate;
```

And for mutations:
```typescript
const addUserMsg = prop_addUserMessage ?? ((text: string) => useConversationStore.getState().addUserMessage(text));
const clearPQ = prop_clearPendingQuestion ?? ((id: string) => useConversationStore.getState().clearPendingQuestion(id));
const interruptMsg = prop_interruptAgentMessage ?? ((name: string) => useConversationStore.getState().interruptAgentMessage(name));
```

This is verbose but correct. The global store hooks always run (satisfying React rules), but their values are ignored when props are provided.

**Step 5: Commit**

```
fix: ChatInput accepts scoped store values via props with global fallback
```

---

### Task 6: Build + TypeScript check

**Step 1: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors in changed files.

**Step 2: Run build**

```bash
cd frontend && npm run build
```

Expected: Clean build.

**Step 3: Commit if build output changed**

```
chore: rebuild frontend for critical defect fixes
```

---

### Task 7: E2E verification

**Test 1: Chat interaction in Context architecture**
1. Start a workflow
2. Wait for `chat.question` event
3. Type answer in ChatInput → verify `pendingQuestionId` resolves
4. Verify answer appears in conversation

**Test 2: Stop & Regenerate**
1. Start a workflow
2. While streaming, click Stop button
3. Verify `interruptAgentMessage` is called on scoped store
4. Type guidance and resume

**Test 3: AgentMessage I/O display**
1. Start a workflow with agent that has I/O
2. After node completes, verify I/O buttons appear on agent message
3. Click to open I/O sheet → verify content shows

**Test 4: Concurrent workflows**
1. Start two workflows
2. Switch between them
3. Verify ChatInput shows correct pending question per workflow

---

## Files Modified

| File | Action |
|------|--------|
| `workflowStores.ts` | Add `_msgCounter` attachment line |
| `AgentMessage.tsx` | Add optional `getAgentIO`/`getNodeState` props |
| `ScopedConversationTab.tsx` | Pass scoped selectors to AgentMessage |
| `ChatInput.tsx` | Add optional props with global fallback |
| `ScopedCenterPanel.tsx` | Read scoped values and pass to ChatInput |
