"""Extension contracts.

Three extension types, picked by **what you want to do**:

  Hook         – observe lifecycle (logging, metrics, persistence).
                 Cannot change anything. Runs concurrently. Never blocks.

  Middleware   – mutate / reject (compact, memory, guardrail, budget).
                 Runs sequentially in registered order. Blocks the agent step.
                 Can raise RejectAction to abort or RetryAction to redo.

  GraphMutator – alter the DAG itself (eval_judge, sub-agent spawn).
                 Runs once at workflow build time. Returns a new Workflow.

If you only need to **watch** what's happening, use Hook. If you need to
**change the prompt / messages / tool args**, use Middleware. If you need
to **add or remove nodes**, use GraphMutator.

Authors: subclass BaseHook / BaseMiddleware / BaseGraphMutator (defined in
this file) and override only the methods you care about. Defaults are no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.api import Workflow


# ============================================================
# Contexts — passed into every extension callback.
# Mutate the fields documented as "mutable"; never reassign ctx itself.
# ============================================================

@dataclass
class WorkflowCtx:
    """Top-level context for a workflow run.

    workflow_id    – stable UUID for this run
    workflow_name  – workflow definition name
    inputs         – original user inputs (read-only)
    metadata       – per-extension scratchpad, keyed by extension name
    """
    workflow_id: str
    workflow_name: str
    inputs: dict[str, Any]
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class AgentConfig:
    """Agent configuration metadata — populated by MacroGraphBuilder.

    Carries all information fed to the agent that isn't already in prompt/messages,
    so extensions (e.g. ConsoleOutput) can display it with toggle switches.
    """
    model: str | None = None
    retries: int = 3
    tools: list[str] = field(default_factory=list)
    tool_info: list[dict] = field(default_factory=list)  # [{name, description}, ...]
    agent_md_path: str | None = None
    critique: str | None = None
    result_type_name: str | None = None
    system_prompt: str | None = None


@dataclass
class NodeCtx:
    """Per-agent-step context.

    workflow            – parent WorkflowCtx
    node_id             – DAG node id (= agent_name for now)
    agent_name          – agent definition name
    prompt              – mutable: the user-message text fed to the LLM this step
    messages            – mutable: full message history (system+user+assistant+tool)
    upstream_outputs    – read-only: outputs from agents this one depends on
    config              – agent configuration metadata (tools, model, paths, etc.)
    metadata            – per-extension scratchpad, keyed by extension name
    _side_effects       – internal: observational artifacts produced by hooks
                          via emit(); cleared after Bus flushes them to WS layer

    emit() — produce an observational artifact (chart, metric, trace) that the
    Bus will flush to WebSocket subscribers after all hooks complete.
    """
    workflow: WorkflowCtx
    node_id: str
    agent_name: str
    prompt: str
    messages: list[dict[str, Any]]
    upstream_outputs: dict[str, Any]
    config: AgentConfig | None = None
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    _side_effects: list[dict] = field(default_factory=list, repr=False)

    def emit(self, event_type: str, payload: dict) -> None:
        self._side_effects.append({"type": event_type, "payload": payload})


@dataclass
class ToolCtx:
    """Per-tool-call context.

    node       – the NodeCtx that owns this tool call
    tool_name  – name of the tool being invoked
    tool_args  – mutable: the args dict; middleware may rewrite (e.g. sandbox path)
    """
    node: NodeCtx
    tool_name: str
    tool_args: dict[str, Any]


# ============================================================
# Middleware control actions.
#
# Returning one of these from a middleware method signals the engine
# to take a specific action instead of continuing normally.
# ============================================================

@dataclass
class RejectAction:
    """Tell the engine: do not run this node / tool. Treat it as failure or skip."""
    reason: str
    propagate_as: Literal["fail", "skip"] = "fail"


@dataclass
class RetryAction:
    """Tell the engine: re-run this node with a new prompt.

    Used by Middleware.after_node when output is judged unsatisfactory.
    """
    new_prompt: str
    max_attempts: int = 1


@dataclass
class SubstituteAction:
    """Tell the engine: replace this tool's result with ``result``.

    Used by Middleware.after_tool (PostToolUse) to rewrite a tool's output
    before it reaches message_history — e.g. compacting a large bash dump
    to a summary + file pointer. Returning it is the EXPLICIT signal that
    the result was transformed, so "who changed what" stays auditable
    (unlike silently returning a different value). The original tool output
    is discarded; if it must be recoverable, the middleware is responsible
    for spilling it to disk and embedding the path in ``result``.
    """
    result: str


# ============================================================
# Extension contracts — all default to no-op so subclasses override
# only what they need.
# ============================================================

class BaseHook:
    """Lifecycle observer. Cannot change anything. Runs concurrently."""

    name: str = "unnamed-hook"

    async def on_workflow_start(self, ctx: WorkflowCtx) -> None:
        return None

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict[str, Any]) -> None:
        return None

    async def on_node_start(self, ctx: NodeCtx) -> None:
        return None

    async def on_node_end(self, ctx: NodeCtx, output: Any) -> None:
        return None

    async def on_llm_delta(self, ctx: NodeCtx, delta: str) -> None:
        return None

    async def on_tool_call(self, ctx: ToolCtx, result: Any) -> None:
        return None


class BaseMiddleware:
    """Mutate / reject in the agent execution path. Runs sequentially.

    Priority: lower runs first in `before_*` phases, higher runs first in
    `after_*` phases (so middleware wraps the agent step like layers).
    """

    name: str = "unnamed-middleware"
    priority: int = 50

    async def before_node(self, ctx: NodeCtx) -> NodeCtx | RejectAction:
        return ctx

    async def after_node(self, ctx: NodeCtx, output: Any) -> Any | RetryAction:
        return output

    async def before_tool(self, ctx: ToolCtx) -> ToolCtx | RejectAction:
        """PreToolUse: run before the tool executes. May rewrite ctx.tool_args
        or return RejectAction to block the call (the model sees ``reason``)."""
        return ctx

    async def after_tool(self, ctx: ToolCtx, result: Any) -> Any | SubstituteAction | RejectAction:
        """PostToolUse: run after the tool returns, before the result reaches
        message_history. Return SubstituteAction(result=...) to replace the
        output (compact/summarize), or RejectAction to flag it as an error.
        Returning ``result`` unchanged is the no-op default."""
        return result


class BaseGraphMutator:
    """Alter the workflow DAG at build time. Runs once before execution.

    Two phases, both invoked by ``Workflow.compile()``:

      mutate()  — in-memory DAG rewrite (insert nodes, rewire edges).
      persist() — durable side files (e.g. agent MD). Default: no-op.

    A mutator that needs to write something to disk so the change survives
    save() should override persist(). The summary file is read at runtime
    via the usual ``resolve_agent_md`` resolution.
    """

    name: str = "unnamed-mutator"

    def mutate(self, workflow: "Workflow") -> "Workflow":
        return workflow

    def persist(self, workflow: "Workflow") -> None:
        return None


# ============================================================
# Protocols (structural) — for `isinstance`-style classification
# inside the Bus without forcing inheritance.
# ============================================================

@runtime_checkable
class HookLike(Protocol):
    name: str
    async def on_workflow_start(self, ctx: WorkflowCtx) -> None: ...


@runtime_checkable
class MiddlewareLike(Protocol):
    name: str
    priority: int
    async def before_node(self, ctx: NodeCtx) -> NodeCtx | RejectAction: ...


@runtime_checkable
class GraphMutatorLike(Protocol):
    name: str
    def mutate(self, workflow: "Workflow") -> "Workflow": ...


# Convenience union for type hints
Extension = BaseHook | BaseMiddleware | BaseGraphMutator
