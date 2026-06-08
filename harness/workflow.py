"""``Workflow`` — declarative workflow definition.

The class is intentionally thin: ``__init__``, ``agents_dir``, ``compile``,
and ``use`` live here. Save/load/list_saved/(de)serialize delegate to
``workflow_persist.py``; run/arun/setup/cleanup/_build_result delegate to
``workflow_runtime.py``. Lazy import inside each wrapper avoids circular
imports between this module and the persist/runtime modules.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from harness.tools.defaults import default_tool_registry
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry
from harness.paths import get_project_root

logger = logging.getLogger(__name__)

_BACKEND_DIR = get_project_root()
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"


def _get_workflows_dir() -> Path:
    """Resolve the workflows directory from the canonical module attribute.

    Phase 6B moved the canonical ``_WORKFLOWS_DIR`` here (from harness.api).
    All read sites go through this getter so they consistently see the
    monkey-patched value — tests should patch ``harness.workflow._WORKFLOWS_DIR``.
    """
    return _WORKFLOWS_DIR


class Workflow:
    """Declarative workflow definition."""

    def __init__(
        self,
        name: str,
        agents: list,
        workflow_dir: Path | None = None,
        agents_dir: str | None = None,  # legacy back-compat — derived from workflow_dir if omitted
        mcp_servers: list[McpServerConfig] | None = None,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
        checkpointer: Any | None = None,
        envelope: dict[str, int] | None = None,
        enable_filesystem_mcp: bool = True,
        enable_codegraph_mcp: bool = True,
        codegraph_path: str | None = None,
    ):
        self.name = name
        self.agents = agents
        # New: workflow_dir is the canonical per-workflow directory.
        # If a legacy agents_dir is passed (and no workflow_dir), keep it for MCP
        # workdir back-compat — its parent doubles as workflow_dir.
        if workflow_dir is not None:
            self.workflow_dir = Path(workflow_dir)
        elif agents_dir is not None:
            # Legacy: treat the directory containing the agents folder as the workflow_dir.
            # If agents_dir already points at a directory called "agents", use its parent;
            # otherwise treat agents_dir itself as the workflow_dir (some old callers passed
            # a flat directory of MDs).
            ad = Path(agents_dir)
            self.workflow_dir = ad.parent if ad.name == "agents" else ad
        else:
            self.workflow_dir = _WORKFLOWS_DIR / name
        self._legacy_agents_dir = agents_dir  # preserved if caller passed it
        self.mcp_servers = mcp_servers or []
        self.tool_registry = tool_registry or ToolRegistry()
        self._event_bus = event_bus
        self.max_iterations = max_iterations
        self.checkpointer = checkpointer
        self.envelope = envelope
        self.enable_filesystem_mcp = enable_filesystem_mcp
        self.enable_codegraph_mcp = enable_codegraph_mcp
        self.codegraph_path = codegraph_path
        self._compiled = None
        self._builder: Any | None = None  # MacroGraphBuilder, set by compile()
        self._mcp_setup_done = False
        self._mcp_bridges: list[McpBridge] = []

    @property
    def agents_dir(self) -> str:
        """Legacy alias — directory holding agent MD files.

        Returns the explicit legacy value if one was passed, else
        ``str(self.workflow_dir / 'agents')`` under the new layout.
        """
        if self._legacy_agents_dir is not None:
            return self._legacy_agents_dir
        return str(self.workflow_dir / "agents")

    def compile(self):
        """Compile the workflow into a LangGraph StateGraph.

        Uses whatever tools are currently in the ToolRegistry.
        If registry is empty, registers default self-built tools (sub_agent + bash).
        Does NOT connect MCP servers — call run() for full setup.

        Also runs the two-phase GraphMutator pipeline:

          1. ``mutator.mutate(workflow)``  — in-memory DAG rewrite
          2. ``mutator.persist(workflow)`` — durable side files (e.g. judge MD)
          3. clear ``eval=True`` on every agent — materialization is one-shot

        After compile() returns, ``save()`` can persist a workflow.json that
        reflects the materialized DAG with no ``eval`` flags remaining.
        """
        from harness.engine.macro_graph import MacroGraphBuilder

        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry(event_bus=self._event_bus)

        # Auto-register built-in Hook plugins (idempotent)
        if self._event_bus is not None:
            from harness.extensions.plugins import register_default_hooks
            register_default_hooks(self._event_bus)

        # Two-phase mutator pipeline: mutate (in-memory) then persist (side files).
        # Persist failures (e.g. summarizer LLM error) propagate — compile aborts.
        if self._event_bus is not None and hasattr(self._event_bus, "get_mutators"):
            for mutator in self._event_bus.get_mutators():
                mutator.mutate(self)
                mutator.persist(self)

        # Any remaining eval=True means no mutator claimed it (e.g. user forgot
        # to .use(EvalJudge())). Fail loud rather than silently strip the flag.
        unhandled = [a.name for a in self.agents if getattr(a, "eval", False)]
        if unhandled:
            from harness.extensions.eval.errors import EvalCompileError
            raise EvalCompileError(
                f"Agents {unhandled} have eval=True but no GraphMutator handled them. "
                f"Call workflow.use(EvalJudge()) before compile()."
            )

        builder = MacroGraphBuilder(
            tool_registry=self.tool_registry,
            event_bus=self._event_bus,
            max_iterations=self.max_iterations,
            envelope=self.envelope,
        )
        graph = builder.build(self)
        self._builder = builder
        compile_kwargs = {}
        if self.checkpointer is not None:
            compile_kwargs["checkpointer"] = self.checkpointer
        self._compiled = graph.compile(**compile_kwargs)
        return self._compiled

    def use(self, extension) -> "Workflow":
        """Register an extension (Hook / Middleware / GraphMutator) on this
        workflow's event bus.

        If no bus was provided at construction time, a local Bus is created
        and reused for subsequent extensions on this workflow.

        Returns self for fluent chaining:

            wf = (
                Workflow("research", agents=[...])
                .use(AutoCompact(threshold_tokens=8000))
                .use(FileMemory(path="./memory.md"))
            )
        """
        if self._event_bus is None:
            from harness.extensions.bus import Bus
            self._event_bus = Bus()
        if not hasattr(self._event_bus, "register"):
            raise TypeError(
                "Workflow.event_bus does not support extensions. "
                "Pass a harness.extensions.bus.Bus instance instead of a "
                "custom event bus, or omit it to create one automatically."
            )
        self._event_bus.register(extension)
        return self

    # ---- Persistence (delegates to workflow_persist) ----

    def save(self) -> Path:
        from harness.workflow_persist import save_workflow
        return save_workflow(self)

    @classmethod
    def load(cls, name: str, agents_dir: str | None = None) -> "Workflow":
        from harness.workflow_persist import load_workflow
        return load_workflow(name, agents_dir)

    @staticmethod
    def list_saved(user_id: str | None = None) -> list[dict]:
        from harness.workflow_persist import list_saved_workflows
        return list_saved_workflows(user_id)

    def to_dict(self) -> dict:
        from harness.workflow_persist import workflow_to_dict
        return workflow_to_dict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict,
        workflow_dir: Path | None = None,
        agents_dir: str | None = None,
        checkpointer: Any | None = None,
    ) -> "Workflow":
        from harness.workflow_persist import workflow_from_dict
        return workflow_from_dict(data, workflow_dir, agents_dir, checkpointer)

    # ---- Runtime (delegates to workflow_runtime) ----

    def run(self, inputs: dict, ui: bool = False, work_dir: str | None = None):
        from harness.workflow_runtime import run_workflow
        return run_workflow(self, inputs, ui=ui, work_dir=work_dir)

    def _launch_ui(self, inputs: dict) -> None:
        from harness.workflow_runtime import _launch_workflow_ui
        _launch_workflow_ui(self, inputs)

    async def arun(self, inputs: dict | None = None, config: dict | None = None,
                   resume_value: Any | None = None):
        from harness.workflow_runtime import arun_workflow
        return await arun_workflow(self, inputs, config=config, resume_value=resume_value)

    async def setup(self, work_dir: str | None = None):
        from harness.workflow_runtime import setup_workflow
        await setup_workflow(self, work_dir=work_dir)

    async def cleanup(self):
        from harness.workflow_runtime import cleanup_workflow
        await cleanup_workflow(self)

    async def _execute(self, inputs: dict, work_dir: str | None = None):
        from harness.workflow_runtime import _execute_workflow
        return await _execute_workflow(self, inputs, work_dir=work_dir)

    def _build_result(self, final_state: dict):
        from harness.workflow_runtime import _build_workflow_result
        return _build_workflow_result(self, final_state)
