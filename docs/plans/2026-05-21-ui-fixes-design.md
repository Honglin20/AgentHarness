# UI Fixes Design — 2026-05-21

Four UI issues addressed together because problem 4 (live/replay unification) touches the same components as problems 1–3.

## Problem 1 — DAG overlaps HeaderBar

**Root cause:** `DAGStatusBar.tsx:160` hardcodes `height: 44`, but dagre computes a larger `svgHeight`. Node labels are drawn at `n.cy - NODE_RADIUS - 4` (above the node), so they overflow the 44-px container and bleed into the HeaderBar.

**Fix:**
- Move node labels **below** the node circle (`n.cy + NODE_RADIUS + 12`)
- Container uses `min-height: 56px` instead of fixed 44; height grows to fit content
- Add `border-b border-app-border` to visually separate from HeaderBar

## Problem 2 — Tab bar + ChatInput must stay pinned

The flex column already does this in theory. To guarantee no shrink behavior:
- Tab bar div: add `shrink-0`
- ChatInput wrapper: add `shrink-0`
- ConversationTab `ScrollArea` keeps `h-full`; parent stays `flex-1 overflow-hidden min-h-0` (already correct)
- DAGStatusBar lives in `page.tsx` above the resizable group (already pinned)

## Problem 3 — Stop-and-regenerate (replaces interrupt)

ChatGPT-style: while an agent is streaming, Send button becomes ■ Stop. Clicking it stops the current LLM call. If the input box has text, that text is treated as user guidance — concatenated with the partial agent output and re-fed to the same agent. The workflow does NOT advance to the next agent.

### New WebSocket protocol (C→S)

```json
{
  "type": "agent.stop_and_regenerate",
  "payload": {
    "workflow_id": "...",
    "agent_name": "...",
    "partial_output": "...",
    "user_guidance": "..."
  }
}
```

### Backend changes (`harness/engine/macro_graph.py` + `server/ws_handler.py`)

- **Delete** `_pending_interrupts`, `request_interrupt`, `_has_pending_interrupt`, `_consume_interrupt`
- **Delete** `workflow.interrupt` branch in `ws_handler.py:125-130`
- **Add** `_pending_stop_regen: dict[str, dict]` keyed by workflow_id, holding `{agent_name, partial_output, user_guidance}`
- **Add** `request_stop_and_regenerate(workflow_id, agent_name, partial_output, user_guidance)`
- **Add** ws handler branch for `agent.stop_and_regenerate`
- At the streaming check point (currently line 265): when a stop_regen is pending for this workflow AND `agent_name` matches the current agent, break the stream and construct the next prompt as:
  - If `user_guidance` non-empty: `partial_output + "\n\n[用户指导]: " + user_guidance`
  - If empty: `partial_output + "\n\n[用户中止了上面的输出，请重新整理思路]"`

### Frontend changes

- `frontend/src/types/events.ts`: remove `"workflow.interrupt"`, add `"agent.stop_and_regenerate"`
- `frontend/src/hooks/useWorkflowEvents.ts`: remove `sendInterrupt`, add `sendStopAndRegenerate(agentName, partialOutput, userGuidance)`
- `frontend/src/stores/conversationStore.ts`: add selector that returns the streaming agent message (most recent with `status === "streaming"`)
- `frontend/src/components/chat/ChatInput.tsx`:
  - Derive `streamingAgent` from store
  - When `streamingAgent` exists: Send button renders as Stop (square icon), `disabled` removed (clickable with empty input)
  - On click: call `sendStopAndRegenerate(streamingAgent.agentName, streamingAgent.content, value)`
  - Remove the old separate Interrupt button block (97-108)
- `SPEC.md` §Interrupt rewritten as §StopAndRegenerate

## Problem 4 — Unified live/replay view

Remove `RunReplayView` as a separate panel. Live workflow and historical runs render through the same DAG + Conversation/Results structure. User switches between them by clicking entries in the history list.

### Backend changes

- `GET /api/runs` now also returns the currently-running workflow as a `RunRecord` with `status: "running"`
- Each `RunRecord` (live and historical) includes a `dag` field (`{nodes, edges, conditional_edges}`)
- A live run's `conversation` / `result.trace` reflects current in-memory state

### Frontend state

- New `viewStore`: `{ activeView: {type:"live"} | {type:"replay", runId} }`
- Default `{type:"live"}`; clicking a history item (including the live one) sets activeView accordingly
- "Live" and "Replay" both feed the same components — selection is purely visual routing

### Components

- `RunHistoryList.tsx`:
  - Refetch on any workflow status change (or via the event bus when a run finishes)
  - Live run gets a breathing dot (pulse animation) icon instead of the green check
  - Click → set `viewStore.activeView`
- `RunReplayView.tsx`: **deleted**
- `CenterPanel.tsx`:
  - Reads activeView; if replay, pulls dag/conversation/results from the selected `RunRecord` (fetched once on selection)
  - Tab bar and ChatInput remain; ChatInput hidden in replay mode (can't send to a frozen run)
- `DAGStatusBar.tsx`: accept optional `dag` + `nodes` props; default to workflowStore (live)
- `ConversationTab.tsx`, `ResultsTab.tsx`: accept optional data props; default to store

### Removal of "Back" button

No Back button needed — user clicks any item in history list (live row included) to switch.

## Implementation order

1. Problem 1 — DAG label position + container height
2. Problem 2 — `shrink-0` guarantees
3. Problem 3 — protocol replacement (backend + frontend), SPEC.md update
4. Problem 4 — backend `/api/runs` live row, viewStore, component refactor, delete RunReplayView

## Out of scope

- Persistence of live-run breathing animation across tab switches (just CSS animation, no state)
- Multiple concurrent workflows (current model is one live workflow at a time)
