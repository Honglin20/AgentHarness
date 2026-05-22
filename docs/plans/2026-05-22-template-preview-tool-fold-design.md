# Template Preview + Tool Call Fold Design

Date: 2026-05-22

## Problem

1. **Left sidebar agents empty until workflow runs.** Selecting a template sets `selectedTemplate` but doesn't populate `workflowStore.dag`, so `AgentBrowser` shows nothing.
2. **Center panel shows "Ready to start" text** instead of a DAG preview when a template is selected but not yet running.
3. **Agent editor opens empty** because `workflowName` isn't set in the store, so the editor can't resolve the correct agent.md path.
4. **Tool calls consume too much space.** Each tool call is a separate expanded card; results auto-expand. With 3+ tools the conversation becomes scroll-heavy.
5. **Conversation styling is rough.** Emoji icons, ▲▼ toggles, thick border-left bars — inconsistent with the rest of the UI.

## Design Decisions

### D1: Write template data into workflowStore on selection (previewTemplate)

When user selects a template, write its `dag`, `agentsDir`, and `workflowName` into `workflowStore` via a new `previewTemplate` action. Status stays `idle`, `workflowId` stays `null`.

- AgentBrowser reads `dag.nodes` → agents appear immediately.
- AgentEditorModal gets `workflowName` → fetches correct agent.md.
- `clearPreview` action resets dag/agentsDir/workflowName when template is deselected.
- `startWorkflow` and `useResetWorkflow` already overwrite all fields, no conflict.

### D2: Center panel renders DAGPreview when idle + dag exists

Replace the "Ready to start xxx" text with a ReactFlow-based DAG preview component. This only appears when `status === "idle"` and `dag` is populated (i.e., template selected, not running).

### D3: ReactFlow for center DAG preview

Use `@xyflow/react` v12 (already installed) for the center preview. Benefits:
- Custom node components showing agent name + description
- Built-in zoom/pan/minimap
- Consistent with project dependencies

Custom node shows:
```
┌──────────────┐
│ Agent Name   │  ← font-semibold
│ description  │  ← line-clamp-2, muted
└──────────────┘
```

The header `DAGStatusBar` (hand-rolled SVG) is unchanged — it serves a different purpose (compact inline status during runs).

### D4: Backend returns agent description in list_saved

Add a `description` field to each agent in `list_saved` response. The backend reads each agent.md, extracts the first non-heading, non-empty line as description. This avoids N client-side fetches.

### D5: Tool calls grouped and folded (Claude Code style)

Replace per-tool `ToolCallMessage` rendering with a `ToolCallGroup` component:
- **Group header**: "Ran N tools" with chevron toggle (only when tools > 1).
- **Each tool**: default collapsed, shows `⚙ toolName key=val…`. Expand for args + result.
- **Auto-expand on result removed**: tools stay collapsed when results arrive.
- Single tool: no group wrapper, rendered inline with the same fold style.

### D6: Tool call styling cleanup

- Replace `⚙` emoji with lucide `Wrench` icon.
- Replace `▲▼` with lucide `ChevronRight`/`ChevronDown` (consistent with agent section).
- Replace `border-l-4` with light `border` + `bg-gray-50`.
- Group header: `bg-muted/50 rounded-md` + tool count badge.

## File Changes

| File | Change |
|------|--------|
| `workflowStore.ts` | +`previewTemplate` action, +`clearPreview` action |
| `CenterPanel.tsx` | Call `previewTemplate` on select; `clearPreview` on deselect; render `DAGPreview` when idle+dag |
| `DAGPreview.tsx` | New: ReactFlow-based preview with custom nodes |
| `DAGPreviewNode.tsx` | New: ReactFlow custom node (name + description) |
| `ToolCallGroup.tsx` | New: collapsible group of tool calls |
| `ToolCallMessage.tsx` | Refactor: default collapsed, style cleanup, remove auto-expand |
| `ConversationTab.tsx` | Render `<ToolCallGroup>` instead of individual `<ToolCallMessage>` |
| `harness/api.py` | `list_saved` returns `description` per agent |
