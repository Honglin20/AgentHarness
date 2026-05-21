# UI Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four UI issues — DAG/HeaderBar overlap, sticky tabs+input layout, ChatGPT-style stop-and-regenerate, unified live/replay history view.

**Architecture:** Issues 1 and 2 are CSS-only. Issue 3 replaces the existing `workflow.interrupt` WS protocol with a richer `agent.stop_and_regenerate` protocol that carries partial output + user guidance. Issue 4 removes the standalone `RunReplayView` and lets the same `CenterPanel` render both live and historical runs via a `viewStore` that routes data sources.

**Tech Stack:** Next.js 14 + Zustand + FastAPI + Pydantic AI + LangGraph. WebSockets for real-time. Tailwind for styling.

**Design doc:** `docs/plans/2026-05-21-ui-fixes-design.md`

---

## Task 1: Fix DAG label overlap with HeaderBar

**Files:**
- Modify: `frontend/src/components/dag/DAGStatusBar.tsx:160` (container) and `:280-288` (label `<text>`)

**Step 1: Move node labels below the circle**

In `DAGStatusBar.tsx`, the `<text>` element rendering each node label currently sits at `y={n.cy - NODE_RADIUS - 4}` (above the circle). Change to:

```tsx
<text
  x={n.cx}
  y={n.cy + NODE_RADIUS + 10}
  textAnchor="middle"
  fontSize={10}
  fill="#374151"
>
  {n.label}
</text>
```

**Step 2: Replace hardcoded height with min-height + border**

In `DAGStatusBar.tsx:160`, replace:

```tsx
<div className="flex items-center justify-center overflow-x-auto" style={{ height: 44 }}>
```

with:

```tsx
<div className="flex items-center justify-center overflow-x-auto border-b border-app-border" style={{ minHeight: 56 }}>
```

**Step 3: Manual verification**

Run dev server: `cd frontend && npm run dev`. Start any workflow. Confirm the DAG node names appear below the circles and do not bleed into the HeaderBar.

**Step 4: Commit**

```bash
git add frontend/src/components/dag/DAGStatusBar.tsx
git commit -m "fix(ui): move DAG node labels below circles and unpin container height"
```

---

## Task 2: Guarantee tab bar and ChatInput stay pinned

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx:152` (tab bar div) and `:189` (ChatInput wrapper)

**Step 1: Add shrink-0 to tab bar**

In `CenterPanel.tsx:153`, change:

```tsx
<div className="flex items-center gap-1 border-b border-app-border px-2 pt-1">
```

to:

```tsx
<div className="flex shrink-0 items-center gap-1 border-b border-app-border px-2 pt-1">
```

**Step 2: Wrap ChatInput in shrink-0 container**

In `CenterPanel.tsx:189-194`, replace:

```tsx
<ChatInput
  sendAnswer={sendAnswer}
  sendInterrupt={sendInterrupt}
  startWorkflow={isIdle ? startWorkflow : undefined}
  alwaysVisible
/>
```

with:

```tsx
<div className="shrink-0">
  <ChatInput
    sendAnswer={sendAnswer}
    sendInterrupt={sendInterrupt}
    startWorkflow={isIdle ? startWorkflow : undefined}
    alwaysVisible
  />
</div>
```

(`sendInterrupt` reference is removed in Task 3; keep this line as-is for now, Task 3 will rename.)

**Step 3: Verify scroll behavior**

Run dev server. Start a workflow. Generate enough messages to scroll. Confirm:
- Conversation/Results tab bar stays at top
- ChatInput stays at bottom
- Only the middle area scrolls

**Step 4: Commit**

```bash
git add frontend/src/components/layout/CenterPanel.tsx
git commit -m "fix(ui): pin tab bar and chat input with shrink-0"
```

---
