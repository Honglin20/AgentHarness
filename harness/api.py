"""harness.api — public API surface (shim).

Implementation split across:
  - types.py             : AgentResult, TokenUsage, NodeTrace, WorkflowResult
  - agent.py             : Agent + _extract_description
  - workflow.py          : Workflow class (thin dispatch table) + _WORKFLOWS_DIR
  - workflow_persist.py  : save / load / list_saved / (de)serialize
  - workflow_runtime.py  : run / arun / setup / cleanup / _build_result
  - benchmark.py         : Benchmark + BenchmarkTaskResult + BenchmarkResult

This file re-exports the names that existing imports rely on. New code
should prefer importing from the specific module (e.g.
``from harness.workflow import Workflow``).
"""
from __future__ import annotations

from harness.agent import Agent, _extract_description
from harness.benchmark import (
    Benchmark,
    BenchmarkResult,
    BenchmarkTaskResult,
)
from harness.types import (
    AgentResult,
    NodeTrace,
    TokenUsage,
    WorkflowResult,
)
from harness.workflow import Workflow

__all__ = [
    "Agent",
    "AgentResult",
    "Benchmark",
    "BenchmarkResult",
    "BenchmarkTaskResult",
    "NodeTrace",
    "TokenUsage",
    "Workflow",
    "WorkflowResult",
    # Module-private names retained for backward compatibility with
    # callers that ``from harness.api import _WORKFLOWS_DIR`` etc.
    "_WORKFLOWS_DIR",
    "_extract_description",
]


def __getattr__(name: str):
    """Dynamic lookup for module-private names that mirror another module.

    ``_WORKFLOWS_DIR`` is defined in ``harness.workflow``; we resolve it
    dynamically here so ``monkeypatch.setattr(harness.workflow, ...)``
    propagates to ``harness.api._WORKFLOWS_DIR`` readers. A plain
    ``from harness.workflow import _WORKFLOWS_DIR`` would bind the value
    at import time and miss the patch.
    """
    if name == "_WORKFLOWS_DIR":
        import harness.workflow as _wf_mod
        return _wf_mod._WORKFLOWS_DIR
    raise AttributeError(f"module 'harness.api' has no attribute {name!r}")
