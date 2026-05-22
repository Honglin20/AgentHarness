# Template Preview + Tool Call Fold Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show DAG preview with agent descriptions when a template is selected, and fold consecutive tool calls into a collapsible group.

**Architecture:** On template selection, write dag/agentsDir/workflowName into workflowStore (previewTemplate action). Center panel detects idle+dag → renders ReactFlow DAG preview. Tool calls are grouped into ToolCallGroup component that defaults to collapsed. Backend adds description field to list_saved.

**Tech Stack:** @xyflow/react v12, zustand, lucide-react, Radix Collapsible, Python pathlib

---

### Task 1: Backend — add description to list_saved

**Files:**
- Modify: `harness/api.py:231-257` (`list_saved` method)
- Test: `tests/test_api_list_saved.py` (new)

**Step 1: Write the failing test**

```python
"""Test that list_saved returns a description field per agent."""
import json
import pytest
from pathlib import Path


def test_list_saved_includes_description(tmp_path, monkeypatch):
    # Set up a minimal workflow directory
    wf_dir = tmp_path / "workflows" / "demo"
    agents_dir = wf_dir / "agents"
    agents_dir.mkdir(parents=True)

    # Write workflow.json
    wf_json = {
        "name": "demo",
        "agents": [{"name": "analyst", "after": []}],
    }
    (wf_dir / "workflow.json").write_text(json.dumps(wf_json))

    # Write agent.md with a description
    (agents_dir / "analyst.md").write_text(
        "---\nname: analyst\n---\nAnalyzes the input data and produces insights.\n\nMore detail here."
    )

    # Patch the workflows dir
    import harness.api as api_mod
    monkeypatch.setattr(api_mod, "_WORKFLOWS_DIR", tmp_path / "workflows")

    from harness.api import Workflow
    result = Workflow.list_saved()

    assert len(result) == 1
    agent = result[0]["agents"][0]
    assert "description" in agent
    assert agent["description"] == "Analyzes the input data and produces insights."
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_api_list_saved.py -v`
Expected: FAIL — `description` key missing from agent dict

**Step 3: Write minimal implementation**

In `harness/api.py`, add a helper function and modify `list_saved`:

```python
# Add near top of file (after imports)
from harness.compiler.md_parser import resolve_agent_md


def _extract_description(agent_name: str, workflow_dir: Path) -> str:
    """Extract the first non-heading, non-empty line from an agent.md as description."""
    try:
        path = resolve_agent_md(agent_name, workflow_dir)
        content = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    in_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""
```

Then in `list_saved`, after building agents list, add description to each:

```python
# Inside list_saved, after: agents = [Agent.from_dict(a) for a in data.get("agents", [])]
# Change the result.append to include description per agent:
agent_dicts = [a.to_dict() for a in agents]
for ad in agent_dicts:
    ad["description"] = _extract_description(ad["name"], f.parent)
result.append({
    "name": data["name"],
    "agents": agent_dicts,
    "dag": {"nodes": node_order, "edges": edges},
    "workflow_dir": str(f.parent),
})
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_list_saved.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add harness/api.py tests/test_api_list_saved.py
git commit -m "feat(api): list_saved returns agent description from agent.md"
```

---

### Task 2: workflowStore — add previewTemplate and clearPreview

**Files:**
- Modify: `frontend/src/stores/workflowStore.ts`

**Step 1: Add previewTemplate and clearPreview actions to the store interface**

Add to `WorkflowState` interface (after `reset`):

```ts
previewTemplate: (template: Record<string, unknown>) => void;
clearPreview: () => void;
```

**Step 2: Implement the actions in the store**

Add to the store implementation (after `reset`):

```ts
previewTemplate: (template) =>
  set({
    workflowName: (template.name as string) ?? null,
    dag: (template.dag as WorkflowState["dag"]) ?? null,
    agentsDir: (template.agents_dir as string) || "agents",
  }),

clearPreview: () =>
  set({
    workflowName: null,
    dag: null,
    agentsDir: "agents",
  }),
```

**Step 3: Verify type check passes**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/stores/workflowStore.ts
git commit -m "feat(store): add previewTemplate and clearPreview actions"
```

---

### Task 3: DAGPreviewNode — ReactFlow custom node

**Files:**
- Create: `frontend/src/components/dag/DAGPreviewNode.tsx`

**Step 1: Create the custom node component**

```tsx
"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

export type DAGPreviewNodeData = {
  label: string;
  description: string;
};

export function DAGPreviewNode({ data }: NodeProps) {
  const { label, description } = data as unknown as DAGPreviewNodeData;
  return (
    <div className="min-w-[150px] max-w-[200px] rounded-lg border border-app-border bg-white px-3 py-2 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-gray-400 !w-2 !h-2" />
      <div className="text-xs font-semibold text-app-text-primary">{label}</div>
      {description && (
        <div className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground">
          {description}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}
```

**Step 2: Verify type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/dag/DAGPreviewNode.tsx
git commit -m "feat(dag): ReactFlow custom node with description"
```

---

### Task 4: DAGPreview — ReactFlow center preview component

**Files:**
- Create: `frontend/src/components/dag/DAGPreview.tsx`

**Step 1: Create the DAGPreview component**

```tsx
"use client";

import { useMemo } from "react";
import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Node, Edge } from "@xyflow/react";
import { DAGPreviewNode } from "./DAGPreviewNode";
import type { DAGShape } from "./DAGStatusBar";

interface DAGPreviewProps {
  dag: NonNullable<DAGShape>;
  /** Agent descriptions keyed by agent name */
  agentDescriptions?: Record<string, string>;
}

const nodeTypes = { preview: DAGPreviewNode };

export function DAGPreview({ dag, agentDescriptions = {} }: DAGPreviewProps) {
  const nodes: Node[] = useMemo(() => {
    return dag.nodes.map((name, i) => ({
      id: name,
      type: "preview",
      position: { x: i * 220, y: 0 },
      data: {
        label: name,
        description: agentDescriptions[name] ?? "",
      },
    }));
  }, [dag.nodes, agentDescriptions]);

  const edges: Edge[] = useMemo(() => {
    const edgeList = dag.edges.map(
      ([source, target]): Edge => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
      })
    );
    for (const ce of dag.conditional_edges ?? []) {
      edgeList.push({
        id: `ce-${ce.from}-${ce.to}`,
        source: ce.from,
        target: ce.to,
        type: "smoothstep",
        label: ce.label,
        style: { stroke: ce.label === "fail" ? "#ef4444" : "#22c55e" },
        labelStyle: { fill: ce.label === "fail" ? "#ef4444" : "#22c55e", fontWeight: 600, fontSize: 10 },
      });
    }
    return edgeList;
  }, [dag.edges, dag.conditional_edges]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="#e5e7eb" gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          pannable
          zoomable
          style={{ border: "1px solid #e5e7eb" }}
        />
      </ReactFlow>
    </div>
  );
}
```

**Step 2: Verify type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/dag/DAGPreview.tsx
git commit -m "feat(dag): ReactFlow DAG preview with fit/zoom/minimap"
```

---

### Task 5: CenterPanel — wire previewTemplate + DAGPreview rendering

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx`

**Step 1: Import DAGPreview and add agent descriptions from template data**

At the top of CenterPanel, add imports:

```ts
import { DAGPreview } from "@/components/dag/DAGPreview";
```

Update the `SavedWorkflow` interface to include agent descriptions:

```ts
interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string; description?: string }[];
  agents_dir?: string;
  dag: { nodes: string[]; edges: [string, string][] };
}
```

**Step 2: Replace setSelectedTemplate calls with previewTemplate**

In the landing page template selection (the `onClick` of template cards), replace:

```tsx
onClick={() => setSelectedTemplate(wf as unknown as Record<string, unknown>)}
```

with:

```tsx
onClick={() => {
  setSelectedTemplate(isSelected ? null : wf as unknown as Record<string, unknown>);
  if (!isSelected) {
    useWorkflowStore.getState().previewTemplate(wf as unknown as Record<string, unknown>);
  } else {
    useWorkflowStore.getState().clearPreview();
  }
}}
```

**Step 3: Replace "Ready to start" with DAGPreview**

Replace the idle+no-replay branch (currently showing "Ready to start"):

```tsx
{isIdle && !isReplay ? (
  <div className="flex h-full items-center justify-center">
    <p className="text-sm text-muted-foreground">Ready to start {(selectedTemplate as Record<string, unknown>)?.name as string}</p>
  </div>
)
```

with:

```tsx
{isIdle && !isReplay ? (
  dag ? (
    <div className="flex h-full flex-col">
      <div className="flex-1">
        <DAGPreview
          dag={dag}
          agentDescriptions={agentDescriptions}
        />
      </div>
      <div className="shrink-0 border-t border-app-border px-4 py-2 text-center">
        <p className="text-xs text-muted-foreground">
          Ready to start <span className="font-medium">{(selectedTemplate as Record<string, unknown>)?.name as string}</span>
        </p>
      </div>
    </div>
  ) : null
)
```

Add `agentDescriptions` computation inside the component:

```ts
const agentDescriptions = useMemo(() => {
  if (!selectedTemplate) return {};
  const wf = selectedTemplate as SavedWorkflow;
  const descMap: Record<string, string> = {};
  for (const a of wf.agents) {
    if (a.description) descMap[a.name] = a.description;
  }
  return descMap;
}, [selectedTemplate]);
```

Also add `dag` from store (it may already be imported, verify):

```ts
const dag = useWorkflowStore((s) => s.dag);
```

**Step 4: Verify type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Manual test — select a template, verify DAG appears in center**

**Step 6: Commit**

```bash
git add frontend/src/components/layout/CenterPanel.tsx
git commit -m "feat(ui): show DAGPreview when template selected, wire previewTemplate"
```

---

### Task 6: ToolCallGroup — collapsible group for consecutive tool calls

**Files:**
- Create: `frontend/src/components/conversation/ToolCallGroup.tsx`

**Step 1: Create the ToolCallGroup component**

```tsx
"use client";

import { useState } from "react";
import { Wrench, ChevronRight, ChevronDown } from "lucide-react";
import type { ConversationMessage } from "@/stores/conversationStore";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

interface ToolCallGroupProps {
  tools: ConversationMessage[];
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

function previewArgs(args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return truncate(args, 60);
  if (typeof args !== "object") return truncate(String(args), 60);
  try {
    const entries = Object.entries(args as Record<string, unknown>);
    if (entries.length === 0) return "";
    const parts = entries.map(([k, v]) => {
      const valStr = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${truncate(valStr ?? "", 40)}`;
    });
    return truncate(parts.join(", "), 80);
  } catch {
    return truncate(JSON.stringify(args), 60);
  }
}

function formatBlock(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

/** Single tool call row — always starts collapsed. */
function ToolRow({ message }: { message: ConversationMessage }) {
  const [open, setOpen] = useState(false);
  const { toolName, toolArgs, toolResult } = message;
  const argsPreview = previewArgs(toolArgs);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-muted/50">
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
        <span className="font-medium">{toolName}</span>
        {argsPreview && (
          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
            {argsPreview}
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-5 rounded border border-app-border bg-gray-50 p-2 text-xs">
          {toolArgs != null && (
            <div className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Args</div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{formatBlock(toolArgs)}</pre>
            </div>
          )}
          {toolResult !== undefined && (
            <div>
              <div className="mb-0.5 text-[10px] font-medium text-muted-foreground">Result</div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">{formatBlock(toolResult)}</pre>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ToolCallGroup({ tools }: ToolCallGroupProps) {
  const [open, setOpen] = useState(false);

  // Single tool — no group wrapper needed
  if (tools.length === 1) {
    return (
      <div className="ml-4">
        <ToolRow message={tools[0]} />
      </div>
    );
  }

  return (
    <div className="ml-4">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md bg-muted/50 px-2.5 py-1.5 text-left text-xs hover:bg-muted">
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="font-medium">
            Ran {tools.length} tools
          </span>
          {!open && (
            <span className="min-w-0 truncate text-[11px] text-muted-foreground">
              {tools.map((t) => t.toolName).join(" · ")}
            </span>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="flex flex-col gap-0.5 py-1">
            {tools.map((t) => (
              <ToolRow key={t.id} message={t} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
```

**Step 2: Verify type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/conversation/ToolCallGroup.tsx
git commit -m "feat(ui): ToolCallGroup — collapsible group for consecutive tools"
```

---

### Task 7: ConversationTab — use ToolCallGroup instead of individual ToolCallMessage

**Files:**
- Modify: `frontend/src/components/conversation/ConversationTab.tsx`
- Modify: `frontend/src/components/conversation/ToolCallMessage.tsx` (simplify to reuse ToolRow or keep as-is for orphan tool calls)

**Step 1: Update ConversationTab imports and rendering**

Replace the import:

```ts
import { ToolCallMessage } from "./ToolCallMessage";
```

with:

```ts
import { ToolCallGroup } from "./ToolCallGroup";
import { ToolCallMessage } from "./ToolCallMessage";
```

Replace the tool rendering in the agent_section block:

```tsx
{!isCollapsed &&
  b.tools.map((t) => <ToolCallMessage key={t.id} message={t} />)}
```

with:

```tsx
{!isCollapsed && <ToolCallGroup tools={b.tools} />}
```

Keep the orphan `ToolCallMessage` usage for standalone tool_call items (line ~107) — those are rare edge cases that don't belong to any agent section.

**Step 2: Verify type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Manual test — run a workflow with multiple tool calls, verify they are grouped and collapsed by default**

**Step 4: Commit**

```bash
git add frontend/src/components/conversation/ConversationTab.tsx
git commit -m "feat(ui): group tool calls in conversation via ToolCallGroup"
```

---

### Task 8: Integration verification

**Step 1: Full type check**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npx tsc --noEmit`
Expected: No errors

**Step 2: Backend test**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_api_list_saved.py -v`
Expected: PASS

**Step 3: Manual end-to-end test**

1. Open app → landing page shows template cards
2. Click a template → center shows ReactFlow DAG with agent names + descriptions
3. Left sidebar shows agents list
4. Click edit on an agent → modal shows actual agent.md content
5. Type task, hit send → workflow runs, center switches to Conversation tab
6. Agent calls multiple tools → they appear grouped/collapsed
7. Click expand on tool group → see individual tools, each also collapsed
8. Click expand on a tool → see args + result
9. Click "New Workflow" → resets to landing page

**Step 4: Push**

```bash
git push
```
