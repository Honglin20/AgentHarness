"""``Benchmark`` — declarative benchmark definition + result models.

A Benchmark is a list of tasks plus an optional prep phase. Running a
benchmark executes every task in parallel against the same workflow and
returns a ``BenchmarkResult``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel as _BaseModel

from harness.agent import Agent
from harness.paths import get_project_root
from harness.tools.registry import ToolRegistry
from harness.types import WorkflowResult

if TYPE_CHECKING:
    pass  # Forward refs only; imports kept inside TYPE_CHECKING to avoid cycles.

logger = logging.getLogger(__name__)

_BACKEND_DIR = get_project_root()
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"


class Benchmark:
    """Declarative benchmark definition.

    Usage::

        bm = Benchmark("quantize-benchmark", description="量化评测")
        bm.prep(type="script", command="bash prep.sh", work_dir="/tmp/repos")
        bm.task("Quantize ResNet", inputs={"model": "resnet50"})
        bm.task("Quantize BERT", inputs={"model": "bert-base"})
        bm.save()

    Prep phase (optional):
        - ``type="script"``: runs a shell command before all tasks.
          Scripts live in ``benchmarks/<name>/``, added to PATH during execution.
          ``work_dir`` controls the execution directory (cwd).
        - ``type="agent"``: runs a single-agent workflow before all tasks.
          Agent MD resolved from ``benchmarks/<name>/agents/`` then ``workflows/_shared/agents/``.
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._prep: dict | None = None
        self._tasks: list[dict] = []

    def prep(
        self,
        type: Literal["script", "agent"],
        command: str | None = None,
        agent: str | None = None,
        work_dir: str | None = None,
    ) -> "Benchmark":
        """Set the prep phase for this benchmark."""
        p: dict = {"type": type}
        if command is not None:
            p["command"] = command
        if agent is not None:
            p["agent"] = agent
        if work_dir is not None:
            p["work_dir"] = work_dir
        self._prep = p
        return self

    def task(self, label: str, inputs: dict | None = None) -> "Benchmark":
        """Add a task to this benchmark."""
        self._tasks.append({
            "label": label,
            "inputs": inputs or {"task": label},
        })
        return self

    def save(self) -> Path:
        """Save benchmark definition to ``benchmarks/<name>/benchmark.json``."""
        from harness.benchmark_store import BenchmarkStore

        store = BenchmarkStore()
        store.save_benchmark(
            name=self.name,
            tasks=self._tasks,
            description=self.description,
            prep=self._prep,
        )
        saved_path = (_BENCHMARKS_DIR / self.name / "benchmark.json").resolve()
        print(f"[Benchmark] saved → {saved_path}")
        return saved_path

    @classmethod
    def load(cls, name: str) -> "Benchmark":
        """Load a benchmark from ``benchmarks/<name>/benchmark.json``."""
        from harness.benchmark_store import BenchmarkStore

        store = BenchmarkStore()
        data = store.load_benchmark(name)
        if data is None:
            raise FileNotFoundError(f"Benchmark '{name}' not found")
        bm = cls(name=data["name"], description=data.get("description", ""))
        bm._tasks = data.get("tasks", [])
        bm._prep = data.get("prep")
        return bm

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "description": self.description,
            "tasks": self._tasks,
        }
        if self._prep:
            d["prep"] = self._prep
        return d

    def run(self, workflow: str, ui: bool = False, plugins: list | None = None) -> "BenchmarkResult":
        """Run this benchmark with the specified workflow. Synchronous.

        Executes prep (if defined), then runs all tasks in parallel.

        Args:
            workflow: Name of the workflow to use for all tasks.
            ui: If True, auto-start server + open browser.
            plugins: Extensions (Hook/Middleware/GraphMutator) to register on each
                     task's Workflow. E.g. ``plugins=[ConsoleOutput()]``
        """
        return asyncio.run(self._execute(workflow, ui=ui, plugins=plugins))

    async def arun(self, workflow: str, plugins: list | None = None) -> "BenchmarkResult":
        """Run this benchmark asynchronously. For callers already in async context."""
        return await self._execute(workflow, ui=False, plugins=plugins)

    async def _execute(self, workflow_name: str, ui: bool = False, plugins: list | None = None) -> "BenchmarkResult":
        # Lazy import to avoid cycle: Workflow needs Benchmark for its __init__-time
        # class resolution, but Benchmark._execute instantiates Workflow.
        from harness.workflow import Workflow

        # 1. Resolve workflow definition
        from harness.registry import get_registry
        try:
            wf_dir = get_registry().resolve_workflow(workflow_name).resource_dir
        except FileNotFoundError:
            wf_dir = _WORKFLOWS_DIR / workflow_name
            if not wf_dir.exists():
                wf_dir = _WORKFLOWS_DIR / "_shared" / "workflows" / workflow_name
        if not (wf_dir / "workflow.json").exists():
            raise FileNotFoundError(f"Workflow '{workflow_name}' not found")

        wf_data = json.loads((wf_dir / "workflow.json").read_text())
        agents_defs = wf_data.get("agents", [])

        # 2. Run prep phase
        if self._prep:
            from harness.prep_executor import run_prep  # , PrepError  # unused import kept for clarity
            await run_prep(self._prep, benchmark_name=self.name)

        # 3. Run all tasks in parallel
        coros = []
        task_labels = []
        for t in self._tasks:
            agents = [Agent.from_dict(a) for a in agents_defs]
            task_wf = Workflow(
                name=f"{self.name}/{t['label']}",
                agents=agents,
                workflow_dir=wf_dir,
                tool_registry=ToolRegistry(),
            )
            # Register plugins on each task's workflow
            if plugins:
                for ext in plugins:
                    task_wf.use(ext)
            inputs = t.get("inputs", {"task": t["label"]})
            coros.append(task_wf._execute(inputs))
            task_labels.append(t["label"])

        results = await asyncio.gather(*coros, return_exceptions=True)

        # 4. Build result
        task_results = []
        for label, r in zip(task_labels, results):
            if isinstance(r, Exception):
                task_results.append(BenchmarkTaskResult(
                    label=label, status="failed", error=str(r),
                ))
            else:
                task_results.append(BenchmarkTaskResult(
                    label=label, status="completed", result=r,
                ))

        bm_result = BenchmarkResult(
            benchmark_name=self.name,
            workflow_name=workflow_name,
            tasks=task_results,
        )

        # 5. UI mode
        if ui:
            self._launch_benchmark_ui(bm_result)

        return bm_result

    def _launch_benchmark_ui(self, result: "BenchmarkResult") -> None:
        import time
        import threading

        port = int(os.environ.get("HARNESS_PORT", "8000"))
        import urllib.request
        try:
            urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1)
        except Exception:
            def _start():
                import uvicorn
                uvicorn.run("server.app:app", host="0.0.0.0", port=port, log_level="warning")
            t = threading.Thread(target=_start, daemon=True)
            t.start()
            time.sleep(2)

        webbrowser.open(f"http://localhost:{port}")


class BenchmarkTaskResult(_BaseModel):
    """Result of a single task within a benchmark run."""
    label: str
    status: Literal["completed", "failed"]
    result: WorkflowResult | None = None
    error: str | None = None


class BenchmarkResult(_BaseModel):
    """Result of a full benchmark run."""
    benchmark_name: str
    workflow_name: str
    tasks: list[BenchmarkTaskResult]

    @property
    def all_completed(self) -> bool:
        return all(t.status == "completed" for t in self.tasks)

    @property
    def failed_tasks(self) -> list[BenchmarkTaskResult]:
        return [t for t in self.tasks if t.status == "failed"]
