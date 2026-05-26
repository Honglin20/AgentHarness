# Left Sidebar + Agent Editor + Run History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a left sidebar with workflow history, template library, and per-workflow agent browser with MD editor + diff comparison, enabling iterative workflow development.

**Architecture:** Three-panel layout (left sidebar 220px | main panel flex-1 | diagnostics 22%). Left sidebar has two sections: top = run history list (grouped by workflow name, clickable to replay), bottom = template library. Agent browser is triggered from the sidebar: clicking an agent opens a modal editor with left-side MD editing + right-side live preview. Diff mode compares agent MD snapshots between two runs. Backend adds run persistence (`runs/` dir), per-workflow agent scoping (`agents/{workflow_name}/` dirs), and CRUD APIs for agent MD files.

**Tech Stack:** react-markdown (already installed), rehype-prism-plus + remark-gfm (already installed), react-diff-viewer-continued (new), shadcn Dialog (new), zustand, FastAPI, file-based persistence (JSON + MD files)

---

## Task 1: Backend — Run persistence

Persist completed workflow runs to `runs/` directory so they survive server restarts.

**Files:**
- Create: `harness/run_store.py`
- Modify: `server/runner.py:99-115`
- Modify: `server/routes.py` (add run list + get endpoints)
- Modify: `server/schemas.py` (add RunInfo schema)
- Test: `tests/test_run_store.py`

### Step 1: Write the failing test

```python
# tests/test_run_store.py
import json
import tempfile
from pathlib import Path

from harness.run_store import RunStore


def test_save_and_list_runs():
    """RunStore persists runs and lists them grouped by workflow name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-001",
            workflow_name="code_review",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are an analyzer."}],
            status="completed",
            inputs={"task": "review foo"},
            result={"outputs": {"analyzer": "ok"}, "errors": {}, "trace": []},
        )

        store.save(
            run_id="run-002",
            workflow_name="code_review",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are a code analyzer."}],
            status="completed",
            inputs={"task": "review bar"},
            result={"outputs": {"analyzer": "done"}, "errors": {}, "trace": []},
        )

        store.save(
            run_id="run-003",
            workflow_name="research",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are a researcher."}],
            status="failed",
            inputs={"task": "research baz"},
            result=None,
        )

        runs = store.list_runs()
        assert len(runs) == 3
        # Most recent first
        assert runs[0]["run_id"] == "run-003"
        assert runs[1]["run_id"] == "run-002"
        assert runs[2]["run_id"] == "run-001"

        # Filter by workflow name
        cr_runs = store.list_runs(workflow_name="code_review")
        assert len(cr_runs) == 2

        # Get single run
        run = store.get_run("run-001")
        assert run["workflow_name"] == "code_review"
        assert run["agents_snapshot"][0]["md_content"] == "You are an analyzer."


def test_get_run_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        assert store.get_run("nonexistent") is None
```

### Step 2: Run test to verify it fails

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_run_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.run_store'`

### Step 3: Implement RunStore

```python
# harness/run_store.py
"""File-based run persistence. Each run is a JSON file in runs/ directory."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_RUNS_DIR = _BACKEND_DIR / "runs"


class RunStore:
    """Persist and query workflow run records."""

    def __init__(self, runs_dir: str | Path | None = None):
        self._dir = Path(runs_dir) if runs_dir else _DEFAULT_RUNS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
    ) -> Path:
        record = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "agents_snapshot": agents_snapshot,
            "status": status,
            "inputs": inputs,
            "result": result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._dir / f"{run_id}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        return path

    def list_runs(self, workflow_name: str | None = None) -> list[dict]:
        runs = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                runs.append(data)
            except (json.JSONDecodeError, KeyError):
                continue
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs

    def get_run(self, run_id: str) -> dict | None:
        path = self._dir / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())
```

### Step 4: Run test to verify it passes

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_run_store.py -v`
Expected: PASS

### Step 5: Integrate RunStore into runner

Modify `server/runner.py` — after workflow completes or fails, save the run record.

Add to `_run_workflow()` after line 100 (where result is stored):

```python
# After: _workflows[workflow_id]["result"] = { ... }
from harness.run_store import RunStore
from harness.compiler.md_parser import parse_agent_md
from pathlib import Path

run_store = RunStore()
agents_snapshot = []
agents_dir = Path(workflow.agents_dir)
for agent_def in workflow.agents:
    md_path = agents_dir / f"{agent_def.name}.md"
    md_content = ""
    if md_path.exists():
        md_content = md_path.read_text()
    agents_snapshot.append({
        "name": agent_def.name,
        "after": agent_def.after,
        "md_content": md_content,
        "tools": agent_def.tools,
        "model": agent_def.model,
        "retries": agent_def.retries,
    })

run_store.save(
    run_id=workflow_id,
    workflow_name=workflow.name,
    agents_snapshot=agents_snapshot,
    status="completed",
    inputs=inputs,
    result=_workflows[workflow_id]["result"],
)
```

Similarly for the failure path — same snapshot logic but `status="failed"` and `result=None`.

### Step 6: Add run API endpoints

Add to `server/routes.py`:

```python
@router.get("/runs")
async def list_runs(workflow_name: str | None = None) -> list[dict]:
    """List persisted run records, optionally filtered by workflow name."""
    from harness.run_store import RunStore
    return RunStore().list_runs(workflow_name=workflow_name)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get a single run record."""
    from harness.run_store import RunStore
    run = RunStore().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
```

Add to `server/schemas.py`:

```python
class AgentSnapshot(BaseModel):
    name: str
    after: list[str] = []
    md_content: str = ""
    tools: list[str] | None = None
    model: str | None = None
    retries: int = 3

class RunInfo(BaseModel):
    run_id: str
    workflow_name: str
    status: str
    inputs: dict = {}
    created_at: str
    agents_count: int
```

### Step 7: Commit

```bash
git add harness/run_store.py tests/test_run_store.py server/runner.py server/routes.py server/schemas.py
git commit -m "feat: add run persistence with RunStore file-based storage"
```

---

## Task 2: Backend — Per-workflow agent scoping + CRUD APIs

Allow different workflows to have same-named agents with different MD content. Add API to read/write agent MD files per workflow.

**Files:**
- Modify: `server/routes.py` (add agent CRUD with agents_dir param)
- Modify: `server/schemas.py` (add AgentMdResponse, UpdateAgentMdRequest)
- Modify: `harness/api.py:144-148` (save() writes agents_dir into JSON)
- Modify: `harness/compiler/md_parser.py` (add write_agent_md function)
- Test: `tests/test_agent_crud.py`

### Step 1: Write the failing test

```python
# tests/test_agent_crud.py
import tempfile
from pathlib import Path

from harness.compiler.md_parser import parse_agent_md, write_agent_md


def test_write_and_reparse_agent_md():
    """write_agent_md produces valid MD that parse_agent_md can read back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "test_agent.md"
        write_agent_md(
            path=md_path,
            name="test_agent",
            prompt="You are a test agent.\nDo the thing.",
            tools=["bash", "read_file"],
            model="deepseek:deepseek-chat",
            retries=5,
        )

        parsed = parse_agent_md(md_path)
        assert parsed.name == "test_agent"
        assert "You are a test agent" in parsed.prompt
        assert parsed.tools == ["bash", "read_file"]
        assert parsed.model == "deepseek:deepseek-chat"
        assert parsed.retries == 5


def test_update_preserves_unmodified_fields():
    """Updating only the prompt preserves other frontmatter fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "test_agent.md"
        write_agent_md(md_path, name="a", prompt="v1", tools=["bash"], model=None, retries=3)

        # Rewrite with new prompt
        write_agent_md(md_path, name="a", prompt="v2", tools=["bash"], model=None, retries=3)

        parsed = parse_agent_md(md_path)
        assert parsed.prompt == "v2"
        assert parsed.tools == ["bash"]
```

### Step 2: Run test to verify it fails

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_agent_crud.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_agent_md'`

### Step 3: Implement write_agent_md

Add to `harness/compiler/md_parser.py`:

```python
import yaml

def write_agent_md(
    path: Path,
    name: str,
    prompt: str,
    tools: list[str] | None = None,
    model: str | None = None,
    retries: int = 3,
    on_pass: str | None = None,
    on_fail: str | None = None,
) -> None:
    """Write an agent Markdown file with YAML frontmatter."""
    metadata = {"name": name, "retries": retries}
    if tools:
        metadata["tools"] = tools
    if model:
        metadata["model"] = model
    if on_pass is not None:
        metadata["on_pass"] = on_pass
    if on_fail is not None:
        metadata["on_fail"] = on_fail

    frontmatter_str = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()
    content = f"---\n{frontmatter_str}\n---\n\n{prompt.strip()}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
```

### Step 4: Run test to verify it passes

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_agent_crud.py -v`
Expected: PASS

### Step 5: Add agent CRUD API endpoints

Add to `server/routes.py`:

```python
@router.get("/agents/{name}/md")
async def get_agent_md(name: str, agents_dir: str = "agents") -> dict:
    """Get the raw Markdown content of an agent definition."""
    md_path = Path(agents_dir) / f"{name}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"name": name, "md_content": md_path.read_text(), "agents_dir": agents_dir}


@router.put("/agents/{name}/md")
async def update_agent_md(name: str, request: Request) -> dict:
    """Update an agent's Markdown file."""
    body = await request.json()
    agents_dir = body.get("agents_dir", "agents")
    md_content = body.get("md_content", "")

    md_path = Path(agents_dir) / f"{name}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    md_path.write_text(md_content)

    # Re-parse to return updated info
    try:
        parsed = parse_agent_md(md_path)
        return {"status": "ok", "name": parsed.name, "description": parsed.description}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid agent MD: {e}")
```

### Step 6: Commit

```bash
git add harness/compiler/md_parser.py server/routes.py server/schemas.py tests/test_agent_crud.py
git commit -m "feat: add write_agent_md + agent CRUD API endpoints"
```

---

## Task 3: Backend — Workflow creation with agents_dir scoping

When creating a workflow, support per-workflow agent directories. The `agents_dir` field in the workflow definition and create request determines which agent MDs are used.

**Files:**
- Modify: `server/routes.py:150-210` (create_workflow uses request.agents_dir)
- Modify: `server/schemas.py:16-20` (agents_dir in CreateWorkflowRequest)
- Modify: `harness/api.py:144-148` (save includes agents_dir)
- Test: `tests/test_workflow_scoping.py`

### Step 1: Write the failing test

```python
# tests/test_workflow_scoping.py
import tempfile
from pathlib import Path
from harness.api import Agent, Workflow
from harness.compiler.md_parser import write_agent_md


def test_workflow_save_load_with_agents_dir():
    """Workflow save/load preserves agents_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir) / "my_workflow_agents"
        agents_dir.mkdir()

        write_agent_md(agents_dir / "analyzer.md", "analyzer", "Scoped analyzer", retries=3)

        wf = Workflow(
            "scoped_wf",
            agents=[Agent("analyzer", after=[])],
            agents_dir=str(agents_dir),
        )
        path = wf.save()

        loaded = Workflow.load("scoped_wf", agents_dir=str(agents_dir))
        assert loaded.agents_dir == str(agents_dir)
        assert loaded.agents[0].name == "analyzer"
```

### Step 2: Run test to verify it fails

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m pytest tests/test_workflow_scoping.py -v`
Expected: May pass if agents_dir is already preserved. Check and adjust.

### Step 3: Ensure agents_dir is persisted in Workflow.to_dict / from_dict

Modify `harness/api.py` `to_dict()`:

```python
def to_dict(self) -> dict:
    return {
        "name": self.name,
        "agents": [a.to_dict() for a in self.agents],
        "agents_dir": self.agents_dir,
    }
```

Modify `from_dict()`:

```python
@classmethod
def from_dict(cls, data: dict, agents_dir: str | None = None) -> Workflow:
    agents = [Agent.from_dict(a) for a in data.get("agents", [])]
    return cls(
        name=data["name"],
        agents=agents,
        agents_dir=agents_dir or data.get("agents_dir", _DEFAULT_AGENTS_DIR),
    )
```

### Step 4: Update WorkflowLauncher to send agents_dir

The frontend `CreateWorkflowRequest` already has `agents_dir` field. The `WorkflowLauncher` component currently hardcodes it to `"agents"`. When a saved workflow definition has a custom `agents_dir`, that value must be sent.

### Step 5: Commit

```bash
git add harness/api.py server/routes.py server/schemas.py tests/test_workflow_scoping.py
git commit -m "feat: per-workflow agents_dir scoping in workflow save/load"
```

---

## Task 4: Frontend — Install dependencies + shadcn Dialog

Install `react-diff-viewer-continued` for agent diff comparison. Add shadcn `Dialog` component for the agent editor modal.

**Files:**
- Modify: `frontend/package.json` (new dep)
- Create: `frontend/src/components/ui/dialog.tsx`

### Step 1: Install react-diff-viewer-continued

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm install react-diff-viewer-continued`

### Step 2: Add shadcn Dialog component

Create `frontend/src/components/ui/dialog.tsx` using the standard shadcn pattern with `@radix-ui/react-dialog` (already installed as a dependency):

```tsx
"use client"

import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

const Dialog = DialogPrimitive.Root
const DialogTrigger = DialogPrimitive.Trigger
const DialogPortal = DialogPrimitive.Portal
const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/80 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-4xl translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col space-y-1.5 text-center sm:text-left", className)} {...props} />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2", className)} {...props} />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight", className)}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
```

### Step 3: Verify build

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -5`
Expected: Build succeeds

### Step 4: Commit

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/ui/dialog.tsx
git commit -m "feat: add react-diff-viewer + shadcn Dialog component"
```

---

## Task 5: Frontend — Run history store

Create a Zustand store for run history data and API interactions.

**Files:**
- Create: `frontend/src/stores/runHistoryStore.ts`

### Step 1: Create the store

```typescript
// frontend/src/stores/runHistoryStore.ts
import { create } from "zustand";

export interface AgentSnapshot {
  name: string;
  after: string[];
  md_content: string;
  tools: string[] | null;
  model: string | null;
  retries: number;
}

export interface RunRecord {
  run_id: string;
  workflow_name: string;
  agents_snapshot: AgentSnapshot[];
  status: string;
  inputs: Record<string, unknown>;
  result: {
    outputs: Record<string, unknown>;
    errors: Record<string, string>;
    trace: Array<{
      agent_name: string;
      status: string;
      duration_ms: number;
      error: string | null;
    }>;
  } | null;
  created_at: string;
}

interface RunHistoryState {
  runs: RunRecord[];
  loading: boolean;
  selectedRunId: string | null;

  fetchRuns: (workflowName?: string) => Promise<void>;
  fetchRun: (runId: string) => Promise<RunRecord | null>;
  selectRun: (runId: string | null) => void;
  reset: () => void;
}

export const useRunHistoryStore = create<RunHistoryState>()((set, get) => ({
  runs: [],
  loading: false,
  selectedRunId: null,

  fetchRuns: async (workflowName?: string) => {
    set({ loading: true });
    try {
      const params = workflowName ? `?workflow_name=${encodeURIComponent(workflowName)}` : "";
      const r = await fetch(`/api/runs${params}`);
      if (r.ok) {
        const runs: RunRecord[] = await r.json();
        set({ runs, loading: false });
      }
    } catch {
      set({ loading: false });
    }
  },

  fetchRun: async (runId: string) => {
    try {
      const r = await fetch(`/api/runs/${runId}`);
      if (r.ok) return await r.json();
    } catch {}
    return null;
  },

  selectRun: (runId) => set({ selectedRunId: runId }),

  reset: () => set({ runs: [], loading: false, selectedRunId: null }),
}));
```

### Step 2: Commit

```bash
git add frontend/src/stores/runHistoryStore.ts
git commit -m "feat: add runHistoryStore for persisted run data"
```

---

## Task 6: Frontend — Sidebar component (layout + history list + templates)

Create the left sidebar with two sections: run history (top) and template library (bottom).

**Files:**
- Create: `frontend/src/components/sidebar/Sidebar.tsx`
- Create: `frontend/src/components/sidebar/RunHistoryList.tsx`
- Create: `frontend/src/components/sidebar/TemplateLibrary.tsx`
- Modify: `frontend/src/app/page.tsx` (add sidebar panel)

### Step 1: Create RunHistoryList

```tsx
// frontend/src/components/sidebar/RunHistoryList.tsx
"use client";

import { useEffect, useMemo } from "react";
import { Clock, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { ScrollArea } from "@/components/ui/scroll-area";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3 w-3 text-emerald-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  running: <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />,
  cancelled: <XCircle className="h-3 w-3 text-gray-400" />,
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function RunHistoryList() {
  const runs = useRunHistoryStore((s) => s.runs);
  const loading = useRunHistoryStore((s) => s.loading);
  const selectedRunId = useRunHistoryStore((s) => s.selectedRunId);
  const fetchRuns = useRunHistoryStore((s) => s.fetchRuns);
  const selectRun = useRunHistoryStore((s) => s.selectRun);
  const workflowStatus = useWorkflowStore((s) => s.status);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Re-fetch when a workflow completes
  useEffect(() => {
    if (workflowStatus === "completed" || workflowStatus === "failed" || workflowStatus === "cancelled") {
      fetchRuns();
    }
  }, [workflowStatus, fetchRuns]);

  // Group runs by workflow_name
  const grouped = useMemo(() => {
    const map = new Map<string, RunRecord[]>();
    for (const run of runs) {
      const key = run.workflow_name;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(run);
    }
    return Array.from(map.entries());
  }, [runs]);

  if (loading && runs.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <p className="px-3 py-4 text-xs text-muted-foreground">
        No runs yet. Start a workflow to see history.
      </p>
    );
  }

  return (
    <ScrollArea className="h-full">
      {grouped.map(([workflowName, workflowRuns]) => (
        <div key={workflowName} className="mb-2">
          <div className="sticky top-0 bg-white px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {workflowName}
          </div>
          {workflowRuns.map((run) => (
            <button
              key={run.run_id}
              onClick={() => selectRun(run.run_id)}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-50 ${
                selectedRunId === run.run_id ? "bg-blue-50" : ""
              }`}
            >
              {STATUS_ICON[run.status] ?? STATUS_ICON.completed}
              <span className="flex-1 truncate text-xs text-app-text-primary">
                {run.inputs?.task
                  ? String(run.inputs.task).slice(0, 40)
                  : run.run_id.slice(0, 8)}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {formatTime(run.created_at)}
              </span>
            </button>
          ))}
        </div>
      ))}
    </ScrollArea>
  );
}
```

### Step 2: Create TemplateLibrary

```tsx
// frontend/src/components/sidebar/TemplateLibrary.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useOutputStore } from "@/stores/outputStore";
import { useChatStore } from "@/stores/chatStore";
import { useChartStore } from "@/stores/chartStore";
import { setActiveWorkflowId } from "@/hooks/useWorkflowEvents";

interface SavedWorkflow {
  name: string;
  agents: { name: string; after: string[]; on_pass?: string; on_fail?: string }[];
  agents_dir?: string;
  dag: { nodes: string[]; edges: [string, string][] };
}

export function TemplateLibrary() {
  const [templates, setTemplates] = useState<SavedWorkflow[]>([]);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState("");
  const setWorkflow = useWorkflowStore((s) => s.setWorkflow);

  useEffect(() => {
    fetch("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: SavedWorkflow[]) => setTemplates(data))
      .catch(() => {});
  }, []);

  const runTemplate = useCallback(
    async (wf: SavedWorkflow) => {
      if (!task.trim()) return;
      setRunning(wf.name);
      useOutputStore.getState().reset();
      useChatStore.getState().reset();
      useChartStore.getState().reset();

      try {
        const agents = wf.agents.map((a) => ({
          name: a.name,
          after: a.after,
          ...(a.on_pass != null ? { on_pass: a.on_pass } : {}),
          ...(a.on_fail != null ? { on_fail: a.on_fail } : {}),
        }));

        const r = await fetch("/api/workflows", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: wf.name,
            agents,
            agents_dir: wf.agents_dir || "agents",
            inputs: { task: task.trim() },
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        setActiveWorkflowId(data.workflow_id);
        setWorkflow(data.workflow_id, wf.name, data.dag);
        setTask("");
      } catch (e: any) {
        console.error("Failed to start workflow:", e.message);
      } finally {
        setRunning("");
      }
    },
    [task, setWorkflow]
  );

  if (templates.length === 0) {
    return (
      <p className="px-3 py-4 text-xs text-muted-foreground">
        No templates. Save a workflow with <code className="rounded bg-muted px-1">wf.save()</code>.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <input
        value={task}
        onChange={(e) => setTask(e.target.value)}
        placeholder="Task description..."
        className="h-7 w-full rounded border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        onKeyDown={(e) => {
          if (e.key === "Enter" && templates.length === 1) runTemplate(templates[0]);
        }}
      />
      {templates.map((wf) => (
        <Button
          key={wf.name}
          variant="outline"
          size="sm"
          className="h-7 justify-start gap-2 text-xs"
          disabled={!task.trim() || running !== ""}
          onClick={() => runTemplate(wf)}
        >
          {running === wf.name ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          {wf.name}
          <span className="ml-auto text-[10px] text-muted-foreground">
            {wf.dag.nodes.length} agents
          </span>
        </Button>
      ))}
    </div>
  );
}
```

### Step 3: Create Sidebar container

```tsx
// frontend/src/components/sidebar/Sidebar.tsx
"use client";

import { Clock, LayoutTemplate } from "lucide-react";
import { RunHistoryList } from "./RunHistoryList";
import { TemplateLibrary } from "./TemplateLibrary";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  return (
    <div className="flex h-full flex-col border-r border-app-border bg-white">
      {/* Run History */}
      <div className="flex items-center gap-2 px-3 py-2">
        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">History</span>
      </div>
      <div className="flex-1 overflow-hidden">
        <RunHistoryList />
      </div>

      <Separator />

      {/* Template Library */}
      <div className="flex items-center gap-2 px-3 py-2">
        <LayoutTemplate className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-app-text-primary">Templates</span>
      </div>
      <div className="max-h-[40%] overflow-auto">
        <TemplateLibrary />
      </div>
    </div>
  );
}
```

### Step 4: Integrate into page.tsx

Replace current two-panel layout with three-panel layout:

```tsx
// frontend/src/app/page.tsx
"use client";

import { Panel, Group, Separator } from "react-resizable-panels";
import { HeaderBar } from "@/components/layout/HeaderBar";
import DAGStatusBar from "@/components/dag/DAGStatusBar";
import { CenterPanel } from "@/components/layout/CenterPanel";
import DiagnosticsPanel from "@/components/diagnostics/DiagnosticsPanel";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useWorkflowStore } from "@/stores/workflowStore";

export default function Home() {
  const status = useWorkflowStore((s) => s.status);

  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
      {status !== "idle" && <DAGStatusBar />}
      <Group orientation="horizontal" className="flex-1">
        <Panel defaultSize="15%" minSize="10%" maxSize="25%">
          <Sidebar />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="60%" minSize="40%">
          <CenterPanel />
        </Panel>
        <Separator className="w-1 bg-app-border hover:bg-blue-400 transition-colors" />
        <Panel defaultSize="25%" minSize="15%" maxSize="35%">
          <DiagnosticsPanel />
        </Panel>
      </Group>
    </div>
  );
}
```

### Step 5: Verify build

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

### Step 6: Commit

```bash
git add frontend/src/components/sidebar/ frontend/src/app/page.tsx
git commit -m "feat: add left sidebar with run history and template library"
```

---

## Task 7: Frontend — Agent editor modal with MD preview

Create a modal dialog for editing agent MD files with live Markdown preview on the right side.

**Files:**
- Create: `frontend/src/components/agent/AgentEditorModal.tsx`

### Step 1: Create the AgentEditorModal

```tsx
// frontend/src/components/agent/AgentEditorModal.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypePrism from "rehype-prism-plus";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Save, RotateCcw } from "lucide-react";

interface AgentEditorModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  agentsDir: string;
}

export function AgentEditorModal({
  open,
  onOpenChange,
  agentName,
  agentsDir,
}: AgentEditorModalProps) {
  const [mdContent, setMdContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // Fetch agent MD content when modal opens
  useEffect(() => {
    if (!open || !agentName) return;
    fetch(`/api/agents/${encodeURIComponent(agentName)}/md?agents_dir=${encodeURIComponent(agentsDir)}`)
      .then((r) => r.json())
      .then((data) => {
        setMdContent(data.md_content ?? "");
        setOriginalContent(data.md_content ?? "");
      })
      .catch(() => setError("Failed to load agent"));
  }, [open, agentName, agentsDir]);

  const isDirty = mdContent !== originalContent;

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError("");
    try {
      const r = await fetch(`/api/agents/${encodeURIComponent(agentName)}/md`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agents_dir: agentsDir, md_content: mdContent }),
      });
      if (!r.ok) throw new Error(await r.text());
      setOriginalContent(mdContent);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }, [agentName, agentsDir, mdContent]);

  const handleReset = useCallback(() => {
    setMdContent(originalContent);
  }, [originalContent]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Agent: <span className="font-mono text-blue-600">{agentName}</span>
          </DialogTitle>
          <DialogDescription className="text-xs">
            Edit the agent&apos;s Markdown definition. Changes apply to future runs only.
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-4 overflow-hidden" style={{ height: "calc(85vh - 140px)" }}>
          {/* Editor pane */}
          <div className="flex flex-1 flex-col">
            <div className="flex items-center justify-between border-b px-1 pb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Edit
              </span>
              <div className="flex gap-1">
                {isDirty && (
                  <Button variant="ghost" size="sm" className="h-6 gap-1 text-xs" onClick={handleReset}>
                    <RotateCcw className="h-3 w-3" /> Reset
                  </Button>
                )}
                <Button
                  size="sm"
                  className="h-6 gap-1 text-xs"
                  disabled={!isDirty || saving}
                  onClick={handleSave}
                >
                  <Save className="h-3 w-3" />
                  {saving ? "Saving..." : saved ? "Saved!" : "Save"}
                </Button>
              </div>
            </div>
            <textarea
              value={mdContent}
              onChange={(e) => setMdContent(e.target.value)}
              className="flex-1 resize-none rounded border border-input bg-gray-50 p-3 font-mono text-xs leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              spellCheck={false}
            />
          </div>

          {/* Preview pane */}
          <div className="flex flex-1 flex-col">
            <div className="border-b px-1 pb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Preview
              </span>
            </div>
            <div className="flex-1 overflow-auto rounded border border-input bg-white p-3">
              <div className="prose prose-sm max-w-none text-xs">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypePrism]}
                >
                  {mdContent}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        </div>

        {error && <p className="text-xs text-red-500">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}
```

### Step 2: Commit

```bash
git add frontend/src/components/agent/AgentEditorModal.tsx
git commit -m "feat: add AgentEditorModal with split MD editor + live preview"
```

---

## Task 8: Frontend — Agent diff comparison modal

Create a modal for comparing agent MD content between two runs (or between current version and a past run).

**Files:**
- Create: `frontend/src/components/agent/AgentDiffModal.tsx`
- Create: `frontend/src/components/agent/RunSelector.tsx`

### Step 1: Create the AgentDiffModal

```tsx
// frontend/src/components/agent/AgentDiffModal.tsx
"use client";

import { useState, useEffect, useMemo } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useRunHistoryStore, type RunRecord } from "@/stores/runHistoryStore";

interface AgentDiffModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  workflowName: string;
}

export function AgentDiffModal({
  open,
  onOpenChange,
  agentName,
  workflowName,
}: AgentDiffModalProps) {
  const runs = useRunHistoryStore((s) => s.runs);
  const [leftRunId, setLeftRunId] = useState<string>("");
  const [rightRunId, setRightRunId] = useState<string>("");

  // Filter runs for this workflow
  const workflowRuns = useMemo(
    () => runs.filter((r) => r.workflow_name === workflowName),
    [runs, workflowName]
  );

  // Auto-select: latest vs second-latest
  useEffect(() => {
    if (workflowRuns.length >= 2) {
      setLeftRunId(workflowRuns[1].run_id); // older
      setRightRunId(workflowRuns[0].run_id); // newer
    } else if (workflowRuns.length === 1) {
      setRightRunId(workflowRuns[0].run_id);
      setLeftRunId("");
    }
  }, [workflowRuns]);

  const leftMd = useMemo(() => {
    if (!leftRunId) return "";
    const run = workflowRuns.find((r) => r.run_id === leftRunId);
    return run?.agents_snapshot.find((a) => a.name === agentName)?.md_content ?? "(agent not found in this run)";
  }, [leftRunId, workflowRuns, agentName]);

  const rightMd = useMemo(() => {
    if (!rightRunId) return "";
    const run = workflowRuns.find((r) => r.run_id === rightRunId);
    return run?.agents_snapshot.find((a) => a.name === agentName)?.md_content ?? "(agent not found in this run)";
  }, [rightRunId, workflowRuns, agentName]);

  const formatRunLabel = (runId: string) => {
    const run = workflowRuns.find((r) => r.run_id === runId);
    if (!run) return "—";
    const d = new Date(run.created_at);
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (${run.status})`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Diff: <span className="font-mono text-blue-600">{agentName}</span>
          </DialogTitle>
          <DialogDescription className="text-xs">
            Compare agent definition between two runs
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-3 py-2">
          <div className="flex flex-1 items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">Old:</span>
            <select
              value={leftRunId}
              onChange={(e) => setLeftRunId(e.target.value)}
              className="h-7 flex-1 rounded border border-input bg-transparent px-2 text-xs"
            >
              <option value="">— select run —</option>
              {workflowRuns.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {formatRunLabel(r.run_id)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-1 items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">New:</span>
            <select
              value={rightRunId}
              onChange={(e) => setRightRunId(e.target.value)}
              className="h-7 flex-1 rounded border border-input bg-transparent px-2 text-xs"
            >
              <option value="">— select run —</option>
              {workflowRuns.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {formatRunLabel(r.run_id)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-auto rounded border" style={{ maxHeight: "calc(85vh - 180px)" }}>
          <ReactDiffViewer
            oldValue={leftMd}
            newValue={rightMd}
            splitView={true}
            compareMethod={DiffMethod.WORDS}
            leftTitle={formatRunLabel(leftRunId) || "—"}
            rightTitle={formatRunLabel(rightRunId) || "—"}
            styles={{
              contentText: { fontSize: "12px", fontFamily: "monospace" },
            }}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

### Step 2: Commit

```bash
git add frontend/src/components/agent/AgentDiffModal.tsx
git commit -m "feat: add AgentDiffModal for comparing agent MD between runs"
```

---

## Task 9: Frontend — Agent browser in sidebar

Add an agent browser section to the sidebar that lists agents for the current workflow. Clicking an agent opens the editor; right-click or button opens diff.

**Files:**
- Create: `frontend/src/components/sidebar/AgentBrowser.tsx`
- Modify: `frontend/src/components/sidebar/Sidebar.tsx` (add AgentBrowser)
- Modify: `frontend/src/stores/workflowStore.ts` (add agentsDir field)

### Step 1: Add agentsDir to workflowStore

Add `agentsDir: string` to `WorkflowState`, set it in `setWorkflow` and `handleWorkflowStarted`.

### Step 2: Create AgentBrowser

```tsx
// frontend/src/components/sidebar/AgentBrowser.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { FileText, GitCompare, Pencil } from "lucide-react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { AgentEditorModal } from "@/components/agent/AgentEditorModal";
import { AgentDiffModal } from "@/components/agent/AgentDiffModal";

interface AgentInfo {
  name: string;
  description?: string;
  model?: string;
  tools?: string[];
}

export function AgentBrowser() {
  const dag = useWorkflowStore((s) => s.dag);
  const agentsDir = useWorkflowStore((s) => s.agentsDir);
  const workflowName = useWorkflowStore((s) => s.workflowName);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [editAgent, setEditAgent] = useState<string | null>(null);
  const [diffAgent, setDiffAgent] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/agents")
      .then((r) => r.json())
      .then((data: AgentInfo[]) => setAgents(data))
      .catch(() => {});
  }, []);

  // Only show agents in current DAG
  const dagAgents = dag
    ? agents.filter((a) => dag.nodes.includes(a.name))
    : agents;

  if (dagAgents.length === 0) {
    return (
      <p className="px-3 py-4 text-xs text-muted-foreground">
        No agents loaded.
      </p>
    );
  }

  return (
    <div className="flex flex-col">
      {dagAgents.map((agent) => (
        <div
          key={agent.name}
          className="group flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-50"
        >
          <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate text-xs text-app-text-primary">
            {agent.name}
          </span>
          <div className="hidden gap-0.5 group-hover:flex">
            <button
              onClick={() => setEditAgent(agent.name)}
              className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary"
              title="Edit agent"
            >
              <Pencil className="h-3 w-3" />
            </button>
            <button
              onClick={() => setDiffAgent(agent.name)}
              className="rounded p-0.5 text-muted-foreground hover:bg-gray-200 hover:text-app-text-primary"
              title="Compare versions"
            >
              <GitCompare className="h-3 w-3" />
            </button>
          </div>
        </div>
      ))}

      {/* Editor Modal */}
      {editAgent && (
        <AgentEditorModal
          open={!!editAgent}
          onOpenChange={(open) => !open && setEditAgent(null)}
          agentName={editAgent}
          agentsDir={agentsDir || "agents"}
        />
      )}

      {/* Diff Modal */}
      {diffAgent && workflowName && (
        <AgentDiffModal
          open={!!diffAgent}
          onOpenChange={(open) => !open && setDiffAgent(null)}
          agentName={diffAgent}
          workflowName={workflowName}
        />
      )}
    </div>
  );
}
```

### Step 3: Add AgentBrowser to Sidebar

Insert between History and Templates sections in `Sidebar.tsx`:

```tsx
{/* Agent Browser — only shown when a workflow is active */}
{status !== "idle" && (
  <>
    <Separator />
    <div className="flex items-center gap-2 px-3 py-2">
      <FileText className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="text-xs font-semibold text-app-text-primary">Agents</span>
    </div>
    <div className="max-h-[30%] overflow-auto">
      <AgentBrowser />
    </div>
  </>
)}
```

### Step 4: Commit

```bash
git add frontend/src/components/sidebar/AgentBrowser.tsx frontend/src/components/sidebar/Sidebar.tsx frontend/src/stores/workflowStore.ts
git commit -m "feat: add agent browser with edit/diff actions in sidebar"
```

---

## Task 10: Frontend — Run history replay

When clicking a past run in the history list, display its conversation and results in the main panel (read-only replay).

**Files:**
- Modify: `frontend/src/stores/runHistoryStore.ts` (add replay state)
- Create: `frontend/src/components/sidebar/RunReplayView.tsx`
- Modify: `frontend/src/components/layout/CenterPanel.tsx` (add replay mode)

### Step 1: Add replay state to runHistoryStore

```typescript
// Add to RunHistoryState:
replayRun: RunRecord | null;
loadReplay: (runId: string) => Promise<void>;
clearReplay: () => void;
```

Implementation:

```typescript
replayRun: null as RunRecord | null,

loadReplay: async (runId: string) => {
  const run = await get().fetchRun(runId);
  set({ replayRun: run });
},

clearReplay: () => set({ replayRun: null, selectedRunId: null }),
```

### Step 2: Create RunReplayView

A simplified read-only view showing the run's agents, their outputs, and errors.

```tsx
// frontend/src/components/sidebar/RunReplayView.tsx
"use client";

import { ArrowLeft, CheckCircle, XCircle, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useRunHistoryStore } from "@/stores/runHistoryStore";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  cancelled: <XCircle className="h-3.5 w-3.5 text-gray-400" />,
};

export function RunReplayView() {
  const run = useRunHistoryStore((s) => s.replayRun);
  const clearReplay = useRunHistoryStore((s) => s.clearReplay);

  if (!run) return null;

  const trace = run.result?.trace ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-app-border px-3 py-2">
        <Button variant="ghost" size="sm" className="h-6 gap-1 text-xs" onClick={clearReplay}>
          <ArrowLeft className="h-3 w-3" /> Back
        </Button>
        <span className="text-xs font-medium text-app-text-primary">{run.workflow_name}</span>
        <span className="text-[10px] text-muted-foreground">
          {new Date(run.created_at).toLocaleString()}
        </span>
        {STATUS_ICON[run.status] ?? STATUS_ICON.completed}
      </div>

      {/* Inputs */}
      {run.inputs && Object.keys(run.inputs).length > 0 && (
        <div className="border-b border-app-border px-3 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Input</span>
          <p className="mt-0.5 text-xs text-app-text-primary">{JSON.stringify(run.inputs, null, 2)}</p>
        </div>
      )}

      {/* Trace */}
      <ScrollArea className="flex-1">
        <div className="p-3">
          {trace.map((t, i) => (
            <div key={i} className="mb-2 rounded border border-app-border p-2">
              <div className="flex items-center gap-2">
                {STATUS_ICON[t.status] ?? <Clock className="h-3.5 w-3.5 text-gray-400" />}
                <span className="text-xs font-medium text-app-text-primary">{t.agent_name}</span>
                {t.duration_ms > 0 && (
                  <span className="text-[10px] text-muted-foreground">{(t.duration_ms / 1000).toFixed(1)}s</span>
                )}
              </div>
              {t.error && <p className="mt-1 text-xs text-red-500">{t.error}</p>}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
```

### Step 3: Integrate into CenterPanel

In `CenterPanel.tsx`, add a replay mode that shows `RunReplayView` when a past run is selected:

```tsx
const replayRun = useRunHistoryStore((s) => s.replayRun);

if (replayRun) {
  return <RunReplayView />;
}
```

Place this check before the `isIdle` check so replay takes priority.

### Step 4: Wire up RunHistoryList click to load replay

In `RunHistoryList.tsx`, update the click handler:

```tsx
const selectRun = useRunHistoryStore((s) => s.selectRun);
const loadReplay = useRunHistoryStore((s) => s.loadReplay);

// On click:
onClick={() => {
  selectRun(run.run_id);
  loadReplay(run.run_id);
}}
```

### Step 5: Commit

```bash
git add frontend/src/stores/runHistoryStore.ts frontend/src/components/sidebar/RunReplayView.tsx frontend/src/components/layout/CenterPanel.tsx frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "feat: add run history replay view with trace display"
```

---

## Task 11: Frontend — Remove WorkflowLauncher from CenterPanel, move to sidebar

The WorkflowLauncher is currently the idle-state view in CenterPanel. Move its functionality into the sidebar's TemplateLibrary. When idle, CenterPanel shows an empty state with a prompt to use the sidebar.

**Files:**
- Modify: `frontend/src/components/layout/CenterPanel.tsx` (replace WorkflowLauncher with empty state)
- Modify: `frontend/src/components/sidebar/TemplateLibrary.tsx` (ensure full launch capability)

### Step 1: Replace WorkflowLauncher in CenterPanel idle state

```tsx
// Replace the isIdle return block:
if (isIdle) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-app-bg-primary">
      <p className="text-sm text-muted-foreground">
        Select a template from the sidebar to start a workflow
      </p>
    </div>
  );
}
```

### Step 2: Commit

```bash
git add frontend/src/components/layout/CenterPanel.tsx
git commit -m "refactor: move workflow launching to sidebar, simplify CenterPanel idle state"
```

---

## Task 12: Frontend — Integration + polish

Wire everything together, test the full flow, and fix any issues.

**Files:**
- Various fixes across all new files

### Step 1: Build and verify

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness/frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds with no errors

### Step 2: Start server and test end-to-end

1. Start backend: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m uvicorn server.app:app --reload --port 8000`
2. Rebuild frontend: `cd frontend && npm run build`
3. Open browser: `http://localhost:8000`
4. Test: sidebar visible with History + Templates sections
5. Test: click template → enter task → run → workflow starts
6. Test: after completion, run appears in History
7. Test: click history item → replay view shows
8. Test: click agent edit icon → modal opens with split editor/preview
9. Test: edit and save → MD file updated
10. Test: click diff icon → modal opens with run comparison
11. Test: panel resizing works between all three panels

### Step 3: Fix any TypeScript or runtime errors

Address any issues found during testing.

### Step 4: Commit

```bash
git add -A
git commit -m "fix: integration fixes for sidebar, agent editor, and run history"
```

---

## Task 13: Backend — Update SPEC.md

Update SPEC.md to document the new APIs and data structures.

**Files:**
- Modify: `SPEC.md` (add §RunStore, update §API table)

### Step 1: Add new API endpoints to §API section

```
| `GET` | `/api/runs` | List persisted run records |
| `GET` | `/api/runs/{run_id}` | Get single run record |
| `GET` | `/api/agents/{name}/md` | Get agent raw Markdown |
| `PUT` | `/api/agents/{name}/md` | Update agent Markdown |
```

### Step 2: Add §RunStore section

Document the run persistence architecture, file format, and the agents_snapshot structure.

### Step 3: Commit

```bash
git add SPEC.md
git commit -m "docs: update SPEC with run persistence and agent CRUD APIs"
```
