# UI Redesign: Conversational Layout with DAG Status Bar

Date: 2026-05-21

## Problem Statement

Current UI has several pain points:
1. Left DAG panel (14%) is too narrow for ReactFlow canvas yet wastes an entire column
2. Right Diagnostics panel (28%) is too wide for sparse content
3. Chart area inside CenterPanel takes 20% height — images are clipped, and empty when no charts
4. Chat area shows "No messages yet" — disconnected from the main agent output flow
5. ask_human / interrupt mechanisms have conceptual overlap with conversational interaction

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DAG placement | Top status bar | Compact, supports parallel/conditional/loop edges, frees left column |
| Interaction paradigm | Conversational main panel | Agent output, charts, user input on same timeline — natural and unified |
| Chart handling | Separate Results Tab | Charts are workflow-level results, not agent output artifacts |
| Chart grouping | By `label`, de-duplicate by `label`+`title` | Same label groups fold together; same title within a group refreshes |
| ask_human | Keep but defer decision | Conversational UI may make it unnecessary; revisit after implementation |

## Layout Structure

```
┌──────────────────────────────────────────────────────┐
│ HeaderBar: Agent Harness │ workflow名 │ [Stop][设置]  │
├──────────────────────────────────────────────────────┤
│ DAGStatusBar: ● analyzer → ● planner → ● reviewer   │  ~48px
├──────────────────────────────────────────┬───────────┤
│                                          │ Diagnostics│
│  [Conversation]  [Results ·2]            │ Trace|Tool │
│ ────────────────────────────────────     │    |Err   │
│                                          │           │
│  Message stream / Results display        │  (detail) │
│  (full width)                            │           │
│                                          │           │
│ ┌────────────────────────────────────┐   │           │
│ │ Input box...                 [Send]│   │           │
│ └────────────────────────────────────┘   │           │
└──────────────────────────────────────────┴───────────┘
```

Proportions: center ~78%, right ~22%. Left column removed entirely.

## Component Changes

### Deleted
- `DAGPanel.tsx` — entire left column
- `DAGCanvas.tsx` — ReactFlow canvas (too heavy for status bar)
- `ChartBar.tsx` — independent chart area
- `AgentStatusBar.tsx` — replaced by DAGStatusBar
- `MessageList.tsx` — replaced by conversation stream
- `StreamingText.tsx` — replaced by conversation messages

### New
- **`DAGStatusBar`** — horizontal DAG visualization (~48px, SVG-based)
- **`ConversationTab`** — chat-style message stream
- **`ResultsTab`** — chart/table display grouped by label

### Modified
- **`CenterPanel.tsx`** — two-tab layout (Conversation + Results), shared input
- **`HeaderBar.tsx`** — already has Stop button, no changes needed
- **`page.tsx`** — remove left panel, add DAGStatusBar
- **`DiagnosticsPanel.tsx`** — add node click highlight from DAGStatusBar

## DAGStatusBar Design

### Rendering
- dagre LR layout + custom SVG rendering (not ReactFlow — too heavy for a status bar)
- Node: 12px colored dot + name label
- Colors: idle=#9CA3AF, running=#3B82F6+pulse, success=#10B981, failed=#EF4444
- Static edges: solid line with arrow
- Conditional edges: dashed line with small label (pass=green, fail=red)
- Loop edges: curved arc arrow, visually distinct from forward edges
- Height: ~48px, horizontally scrollable when nodes overflow
- Click node → highlight corresponding trace in Diagnostics panel

### Data Source
Same `workflowStore.dag` structure:
```ts
dag: {
  nodes: string[],
  edges: [string, string][],
  conditional_edges: { from: string; to: string; label: string }[]
}
```

## Conversational Message Model

### Message Types

| Type | Alignment | Rendering |
|------|-----------|-----------|
| `agent` | Left | Agent name + status badge, streaming markdown body |
| `tool_call` | Left (indented) | Collapsible card: tool name + args summary; contains tool_result inside |
| `user` | Right | ChatGPT-style right-aligned bubble |
| `system` | Center | Gray text: "workflow started", "interrupt received" |

### Data Model

```ts
interface ChatMessage {
  id: string;
  type: "agent" | "user" | "tool_call" | "system";
  nodeId?: string;
  agentName?: string;
  content: string;
  toolName?: string;
  toolArgs?: object;
  toolResult?: string;
  status?: "streaming" | "done" | "error";
  timestamp: number;
}
```

### Event → Message Mapping

| Event | Action |
|-------|--------|
| `node.started` | Append new `agent` message with status=streaming |
| `agent.text_delta` | Append text to current agent message's content |
| `agent.tool_call` | Append new `tool_call` message |
| `agent.tool_result` | Fill toolResult on most recent matching tool_call |
| `node.completed` | Set agent message status=done, add duration badge |
| `node.failed` | Set agent message status=error, add error content |
| `chat.question` | Append agent message with question content, change input placeholder |
| `chat.answer` | Append `user` message |
| `user input` | Append `user` message |
| `workflow.started` | Append `system` message |
| `workflow.resumed` | Append `system` message |

### ask_human Interaction

No inline input widget. Questions appear as regular agent messages in the stream. User answers via the shared bottom input box. Input placeholder changes contextually:
- Default: `"Message..."`
- Pending question: `"回答 {agent_name} 的问题..."`

One pending question at a time — no ambiguity.

## Results Tab Design

### Layout
- Full width/height card groups, one per `label`
- Cards within a group are collapsible (click group header to toggle)
- Each card renders a chart or table at full size (no more 20% height clipping)

### Grouping & De-duplication
- Group key = `label`
- Unique key within group = `label` + `title`
- Same `label` + `title` → replace existing chart (refresh, not append)
- Tab badge shows number of groups (not individual charts)

### Empty State
"No results yet. Results will appear here when agents produce charts or tables."

### Shared Input Box
Input box is shared between Conversation and Results tabs. Always visible at bottom regardless of active tab.

## Diagnostics Panel

Proportion reduced from 28% to ~22%. No structural changes. One enhancement:
- **DAG node click → Diagnostics highlight**: clicking a node in DAGStatusBar auto-switches to Trace tab and highlights the corresponding entry.

## LangSmith Integration Roadmap

### Phase 1 — Observability Enhancements (small changes, high value)
| Feature | Integration |
|---------|-------------|
| Cost tracking | Per-model pricing table in backend; `cost` field in node.completed events; show $ on DAG nodes |
| Token subtypes | Extend TokenUsage with reasoning/text breakdown; display in Diagnostics |
| Feedback scoring | Thumbs up/down per agent message; store in backend; optional LangSmith API sync |

### Phase 2 — Debugging Capabilities (medium changes)
| Feature | Integration |
|---------|-------------|
| Hierarchical trace | Store `all_messages()` detail per node; render Trace tab as expandable tree |
| State snapshots | Save state after each node completes; UI fetches on node click |
| Prompt playground | New UI entry: select agent + input → call arun directly |

### Phase 3 — Evaluation & Automation (large changes, future)
| Feature | Integration |
|---------|-------------|
| Dataset collection | Save completed workflow as test case |
| LLM-as-judge | Auto-score each agent output |
| Monitoring dashboards | Time-series: cost, latency, error rate |

## Open Questions

- [ ] **ask_human necessity**: Conversational UI may make ask_human redundant. Keep for now, revisit after implementation.
- [ ] **Loop visualization in SVG**: Curved arc for back-edges needs design refinement — ensure readability when multiple loops exist.
