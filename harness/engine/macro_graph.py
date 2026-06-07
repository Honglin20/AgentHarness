from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, ValidationError
from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import ParsedAgent, parse_agent_md, resolve_agent_md
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.extensions.base import AgentConfig, NodeCtx, RejectAction, RetryAction, WorkflowCtx
from harness.engine.llm_executor import LLMExecutor
from harness.engine.stop_signal import StopSignalManager
from harness.extensions.bus import safe_emit
from harness.extensions.envelope import check_envelope
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.cost import calculate_cost
from harness.tools.deps import AgentDeps
from harness.tools.todo_reminder import TodoReminderTracker

logger = logging.getLogger(__name__)
from harness.tools.registry import ToolRegistry


# Registry of active builders keyed by workflow_id, used by the module-level
# request_stop_and_regenerate shim to forward to the correct builder instance.
_active_builders: dict[str, "MacroGraphBuilder"] = {}


async def request_stop_and_regenerate(
    workflow_id: str,
    agent_name: str,
    partial_output: str,
    user_guidance: str,
) -> None:
    """Module-level shim: forwards to the active builder's signal manager.

    Kept for backward compatibility with ws_handler imports.
    """
    logger.warning(
        "[DIAG-STOP-1] request_stop_and_regenerate called: "
        "wf=%s agent=%s guidance=%r partial_len=%d has_builder=%s",
        workflow_id, agent_name, user_guidance[:50], len(partial_output),
        workflow_id in _active_builders,
    )
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        await builder.request_stop_and_regenerate(
            agent_name, partial_output, user_guidance,
        )
    else:
        logger.warning(
            "[DIAG-STOP-1] No active builder for wf=%s", workflow_id,
        )


def clear_stop_regen(workflow_id: str) -> None:
    """Clear any pending stop-and-regenerate signal for a workflow.

    Called when a workflow is cancelled/paused to prevent stale signals
    from triggering immediate interrupts on resume.
    """
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        builder._signal_mgr.clear(workflow_id)


def _save_incremental(builder, event_bus):
    """Best-effort incremental save after each node completes.

    Persists agent_io + derived conversation to disk so that switching
    to a running workflow always fetches authoritative data from backend.
    Never raises — if save fails, the workflow continues normally.
    """
    try:
        from harness.run_store import RunStore
        from harness.extensions.collectors import build_conversation, ChartCollector
        from server.repository import get_repository

        wid = builder.workflow_id
        if not wid:
            return

        repo = get_repository()
        data = repo.get(wid)
        if not data or not data.get("workflow"):
            return

        conversation = build_conversation(dict(builder.agent_io))

        chart_groups = None
        if event_bus:
            cc = ChartCollector(event_bus)
            cg = cc.get_chart_groups()
            if cg.get("groupOrder"):
                chart_groups = cg

        RunStore().save(
            run_id=wid,
            workflow_name=data["workflow"].name,
            agents_snapshot=data.get("agents_snapshot", []),
            status="running",
            inputs=data.get("inputs", {}),
            result=None,
            dag=repo.get_dag(wid),
            agent_io=dict(builder.agent_io),
            batch_id=data.get("batch_id"),
            user_id=data.get("user_id"),
            conversation=conversation,
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
        )
    except Exception:
        pass


class ReviewDecision(BaseModel):
    """Default result_type for agents with conditional edges."""
    decision: Literal["pass", "fail"]
    reason: str
    score: float | None = None


def _strip_schema(schema: dict) -> dict:
    """Remove fields from JSON Schema that add no value for LLMs.

    Strips: title, description (on the type itself, not on properties),
    anyOf [{type}, {type: null}] → inline "| null", default: null.
    Keeps: type, description (on properties), required, properties, items, enum.
    """
    if not isinstance(schema, dict):
        return schema

    out = {}
    for k, v in schema.items():
        if k in ("title", "default"):
            continue
        if k == "anyOf" and isinstance(v, list) and len(v) == 2:
            types = [e.get("type") for e in v if isinstance(e, dict)]
            has_ref = any("$ref" in e for e in v if isinstance(e, dict))
            if "null" in types and not has_ref:
                non_null = [t for t in types if t != "null" and t is not None]
                if non_null:
                    out["type"] = f"{non_null[0]} | null"
                    continue
        if k == "description" and "properties" in schema:
            # Skip top-level description (class docstring), keep property descriptions
            continue
        if isinstance(v, dict):
            out[k] = _strip_schema(v)
        elif isinstance(v, list):
            out[k] = [_strip_schema(i) for i in v]
        else:
            out[k] = v
    return out


def _validate_output(output, result_type):
    """Validate agent output against its result_type.

    Returns None if valid, or an error string if validation fails.
    """
    if result_type is None:
        return None
    if output is None:
        return "Agent produced no output (interrupted or failed)"
    if not isinstance(output, BaseModel):
        return f"Expected {result_type.__name__}, got {type(output).__name__}"
    try:
        output.model_validate(output.model_dump())
    except ValidationError as e:
        return f"Output validation failed: {e}"
    return None


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
        envelope: dict[str, int] | None = None,
    ):
        self.tool_registry = tool_registry or ToolRegistry()
        self.event_bus = event_bus
        self.max_iterations = max_iterations
        self.envelope = envelope
        self.workflow_id: str | None = None  # Set by runner before execution
        self._workflow_name: str = ""  # Set by build()
        self.agent_io: dict[str, dict] = {}  # Collected per-node I/O for persistence

        # Stop-and-regenerate signal management (delegated to StopSignalManager)
        self._signal_mgr = StopSignalManager()

        # ChatGPT-style stop: asyncio.Event-based guidance waiting.
        # These fields are kept for backward compatibility with tests that
        # access them directly. They delegate to _signal_mgr.
        # When Stop is clicked with empty guidance, nodeFunc emits
        # workflow.waiting_for_guidance and awaits this event.
        # When user submits guidance, provide_guidance() sets it.

        # Register event-bus-dependent tools when event_bus is available
        if event_bus:
            if "ask_user" not in self.tool_registry.list_tools():
                from harness.tools.ask_user import AskUserToolFactory
                self.tool_registry.register("ask_user", AskUserToolFactory(event_bus=event_bus))
            if "render_chart" not in self.tool_registry.list_tools():
                from harness.tools.chart import RenderChartToolFactory
                self.tool_registry.register("render_chart", RenderChartToolFactory(event_bus=event_bus))

        self.micro_factory = MicroAgentFactory(tool_registry=self.tool_registry)

    # ---- Stop & Regenerate instance methods (delegate to StopSignalManager) ----

    @property
    def _guidance_event(self) -> asyncio.Event | None:
        """Backward-compatible property for tests."""
        wid = self.workflow_id or ""
        return self._signal_mgr._guidance_events.get(wid)

    @_guidance_event.setter
    def _guidance_event(self, value: asyncio.Event | None) -> None:
        wid = self.workflow_id or ""
        if value is None:
            self._signal_mgr._guidance_events.pop(wid, None)
        else:
            self._signal_mgr._guidance_events[wid] = value

    @property
    def _pending_guidance(self) -> str:
        """Backward-compatible property for tests."""
        wid = self.workflow_id or ""
        return self._signal_mgr._guidance_values.get(wid, "")

    @_pending_guidance.setter
    def _pending_guidance(self, value: str) -> None:
        wid = self.workflow_id or ""
        self._signal_mgr._guidance_values[wid] = value

    @property
    def _pending_stop_regen(self) -> dict[str, dict[str, str | float]]:
        """Backward-compatible property for tests."""
        return self._signal_mgr._pending

    async def request_stop_and_regenerate(
        self,
        agent_name: str,
        partial_output: str,
        user_guidance: str,
    ) -> None:
        """Request stop + regenerate for a specific agent in this workflow.

        Delegates to StopSignalManager.store().
        """
        wid = self.workflow_id or ""
        await self._signal_mgr.store(wid, agent_name, partial_output, user_guidance)

    async def await_guidance(self, timeout: float = 300.0) -> str:
        """Block until user provides guidance via provide_guidance().

        Returns the guidance string, or "" on timeout.
        Delegates to StopSignalManager.await_guidance().
        """
        wid = self.workflow_id or ""
        return await self._signal_mgr.await_guidance(wid, timeout=timeout)

    async def provide_guidance(self, guidance: str) -> None:
        """Set guidance and wake up the waiting nodeFunc.

        Delegates to StopSignalManager.provide_guidance().
        """
        wid = self.workflow_id or ""
        await self._signal_mgr.provide_guidance(wid, guidance)

    def _has_pending_stop_regen(self, workflow_id: str, agent_name: str) -> bool:
        """Check if there's a pending signal. Delegates to StopSignalManager."""
        return self._signal_mgr.has_pending(workflow_id, agent_name)

    def _consume_stop_regen(self, workflow_id: str) -> dict[str, str] | None:
        """Consume and return the signal. Delegates to StopSignalManager."""
        return self._signal_mgr.consume(workflow_id)

    def register_active(self) -> None:
        """Register this builder as the active one for its workflow_id.

        Called by runner after setting workflow_id.  Enables the module-level
        request_stop_and_regenerate shim to forward signals here.
        """
        if self.workflow_id:
            _active_builders[self.workflow_id] = self

    def unregister_active(self) -> None:
        if self.workflow_id:
            _active_builders.pop(self.workflow_id, None)

    def build(self, workflow) -> StateGraph:
        """Build a LangGraph StateGraph from a Workflow definition.

        Mutators are invoked by ``Workflow.compile()`` (two-phase mutate+persist),
        not here. By the time we see the workflow, the DAG is final.
        """
        self._workflow_name = workflow.name

        agents = workflow.agents
        workflow_dir = workflow.workflow_dir

        # Parse all agent MD files via resolve_agent_md (private first, shared fallback)
        # Skip passthrough nodes (no MD on disk)
        parsed_agents = {}
        agent_md_paths = {}
        for agent in agents:
            if "_passthrough" in agent.name:
                continue  # passthrough node — no MD file
            try:
                md_path = resolve_agent_md(agent.name, workflow_dir)
                agent_md_paths[agent.name] = str(md_path)
                parsed = parse_agent_md(md_path)
            except (FileNotFoundError, ValueError):
                # MD missing or malformed (e.g. idempotent re-compile after
                # external corruption). Fall back to bare prompt — the agent
                # definition in workflow.json carries result_type and tools.
                parsed = ParsedAgent(name=agent.name, prompt="")
            parsed_agents[agent.name] = parsed

        # Build execution order (static edges only)
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

        # Build judge→target mapping for upstream injection.
        # When a downstream agent depends on a judge, it also needs the
        # judge's eval_target output (e.g. runner needs configurator's
        # AdapterConfig, not the judge's ReviewDecision).
        judge_targets = {}
        for agent in agents:
            et = getattr(agent, "eval_target", None) or getattr(agent, "_eval_target", None)
            if et:
                judge_targets[agent.name] = et

        # Merge on_pass/on_fail from parsed MD into agent defs
        for agent in agents:
            if agent.name not in parsed_agents:
                continue
            parsed = parsed_agents[agent.name]
            if agent.on_pass is None and parsed.on_pass is not None:
                agent.on_pass = parsed.on_pass
            if agent.on_fail is None and parsed.on_fail is not None:
                agent.on_fail = parsed.on_fail

        # Build the StateGraph
        graph = StateGraph(HarnessState)

        # Add nodes (async node functions)
        for agent_name in execution_order:
            agent_def = agent_map[agent_name]
            is_passthrough = "_passthrough" in agent_name

            if is_passthrough:
                node_func = self._make_passthrough_node_func(agent_def)
            else:
                parsed = parsed_agents[agent_name]
                node_func = self._make_node_func(agent_def, parsed, dep_map, workflow_dir, agent_md_paths.get(agent_name, ""), judge_targets)
            graph.add_node(agent_name, node_func)

        # Collect conditional edge targets — these are activated by routing,
        # not by START, even if they have no `after` dependency.
        # Exception: a node that is a root (no deps) should still get START edge
        # even if it's a conditional target (for retry/loop scenarios).
        conditional_targets = set()
        # Track agents with after=None (only trigger via conditional edges)
        conditional_only_nodes = set()
        # Track source nodes that have conditional edges — their outgoing
        # routing is fully controlled by conditional edges, so static edges
        # from them must be skipped to avoid conflicting paths.
        conditional_source_nodes = set()
        for agent in agents:
            if agent.after is None:
                conditional_only_nodes.add(agent.name)
            if agent.has_conditional_edges:
                conditional_source_nodes.add(agent.name)
                if agent.on_pass is not None:
                    conditional_targets.add(agent.on_pass)
                if agent.on_fail is not None:
                    conditional_targets.add(agent.on_fail)

        # Build a set of root nodes (agents with no static dependencies)
        root_nodes = {agent_name for agent_name, deps in dep_map.items() if deps is not None and not deps}

        # Add edges from START to root nodes
        # Exclude nodes that are conditional-only (after=None)
        # Include root nodes that are also conditional targets (for retry/loop)
        for agent_name in execution_order:
            if agent_name in root_nodes and agent_name not in conditional_only_nodes:
                graph.add_edge(START, agent_name)

        # Add edges between dependent nodes
        # Skip static edges FROM nodes that have conditional edges — their
        # routing is handled entirely by add_conditional_edges below.
        for agent_name in execution_order:
            deps = dep_map[agent_name] or []
            for dep in deps:
                if dep in conditional_source_nodes:
                    continue
                graph.add_edge(dep, agent_name)

        # Track which nodes have conditional edges
        conditional_nodes = set()

        # Add conditional edges for agents with on_pass/on_fail
        for agent in agents:
            if agent.has_conditional_edges:
                conditional_nodes.add(agent.name)
                targets = {}
                targets["pass"] = agent.on_pass if agent.on_pass is not None else END
                targets["fail"] = agent.on_fail if agent.on_fail is not None else END

                # All nodes route from outputs (ReviewDecision.decision or
                # plain string) — no metadata special-casing.
                router = lambda state, an=agent.name: _route_decision(state, an)

                graph.add_conditional_edges(
                    agent.name,
                    router,
                    targets,
                )

        # Add edges from leaf nodes to END (only if no conditional edges)
        downstream = set()
        for deps in dep_map.values():
            if deps:
                downstream.update(deps)
        # Add conditional edge targets to downstream
        for agent in agents:
            if agent.on_pass is not None:
                downstream.add(agent.on_pass)
            if agent.on_fail is not None:
                downstream.add(agent.on_fail)

        for agent_name in execution_order:
            if agent_name not in downstream and agent_name not in conditional_nodes:
                graph.add_edge(agent_name, END)

        return graph

    def _resolve_agent_config(self, agent_def, parsed):
        """Merge tools, model, retries from API definition and MD file.

        Returns (final_tool_names, model, retries, result_type).
        """
        md_tools = parsed.tools
        api_tools = agent_def.tools or []
        if not md_tools and not api_tools:
            final_tool_names = None  # → resolve() loads all
        else:
            final_tool_names = md_tools + [t for t in api_tools if t not in md_tools]
            final_tool_names = self.tool_registry.expand_globs(final_tool_names, strict=False)

        model = agent_def.model or parsed.model
        retries = parsed.retries
        result_type = agent_def.result_type

        # Auto-inject ReviewDecision if agent has conditional edges and no result_type
        if agent_def.has_conditional_edges and result_type is None:
            result_type = ReviewDecision

        return final_tool_names, model, retries, result_type

    def _make_node_func(self, agent_def, parsed, dep_map, workflow_dir, md_path="", judge_targets=None):
        """Create an async LangGraph node function for an agent."""
        micro_factory = self.micro_factory
        bus = self.event_bus
        max_iterations = self.max_iterations
        builder_self = self  # Capture for workflow_id access
        final_tool_names, model, retries, result_type = self._resolve_agent_config(agent_def, parsed)

        # Per-node reminder tracker (only when todo is available).
        # Tracker reads TodoState lazily from deps — the todo tool creates state
        # on first call, and the tracker reads it from there.  No registry mutation.
        todo_available = final_tool_names is None or "todo" in final_tool_names
        # Will be set inside nodeFunc after deps is created
        _reminder_tracker_holder: list[TodoReminderTracker | None] = [None]

        tool_info = micro_factory.tool_registry.get_tool_info(final_tool_names)
        upstream_names = dep_map[agent_def.name] or []
        _judge_targets = judge_targets or {}

        # Build augmented system prompt with output format schema
        augmented_prompt = parsed.prompt
        if result_type is not None:
            try:
                import json as _json
                schema = _strip_schema(result_type.model_json_schema())
                augmented_prompt += (
                    "\n\n## Output Format\n"
                    "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n"
                    "When finished, respond with JSON matching this schema (no markdown fences):\n"
                    + _json.dumps(schema, indent=2, ensure_ascii=False)
                )
            except Exception:
                pass

        async def node_func(state: HarnessState) -> dict:
            start_time = time.time()

            # Check iteration count for conditional edges
            if agent_def.has_conditional_edges:
                iter_key = f"{agent_def.name}_loop"
                current_count = state.get("iteration_counts", {}).get(iter_key, 0)
                if current_count >= max_iterations:
                    if bus:
                        safe_emit(bus,"node.failed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": f"Max iterations ({max_iterations}) reached for conditional edge loop",
                            "error_type": "MaxIterationsError",
                            "duration_ms": 0,
                            "attempt": 1,
                            "will_retry": False,
                        })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: f"Max iterations ({max_iterations}) exceeded"},
                        STATE_METADATA: {},
                        "iteration_counts": {iter_key: current_count},
                    }

            # Emit node.started event (legacy WS path)
            if bus:
                safe_emit(bus,"node.started", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": agent_def.name,
                    "agent_name": agent_def.name,
                    "attempt": 1,
                    "tools": tool_info,
                    "model": model,
                })

            # Check if any upstream dependency has failed — skip this node
            upstream_errors = state.get(STATE_ERRORS, {})
            for dep_name in upstream_names:
                if dep_name in upstream_errors:
                    if bus:
                        safe_emit(bus,"node.failed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": f"Skipped: upstream '{dep_name}' failed",
                            "error_type": "UpstreamDependencyError",
                            "duration_ms": 0,
                            "attempt": 1,
                            "will_retry": False,
                        })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: f"Skipped: upstream '{dep_name}' failed: {upstream_errors[dep_name]}"},
                        STATE_METADATA: {agent_def.name: {"duration_ms": 0, "skipped": True}},
                    }

            # Gather upstream outputs
            upstream_outputs = {}
            outputs = state.get(STATE_OUTPUTS, {})
            for dep_name in upstream_names:
                if dep_name in outputs:
                    upstream_outputs[dep_name] = outputs[dep_name]

            # If any upstream dep is a judge, also inject its eval_target output.
            # e.g. runner depends on _judge_configurator, but needs configurator's
            # AdapterConfig (not the judge's ReviewDecision).
            for dep_name in upstream_names:
                target_name = _judge_targets.get(dep_name)
                if target_name and target_name in outputs and target_name not in upstream_outputs:
                    upstream_outputs[target_name] = outputs[target_name]

            # Extract critique from judge output (if this agent is retrying after a fail)
            critique = None

            # Check upstream deps (normal case: downstream of a judge)
            for dep_name in upstream_names:
                if dep_name.startswith("_judge_"):
                    judge_output = outputs.get(dep_name)
                    if hasattr(judge_output, 'decision') and judge_output.decision == "fail":
                        critique = getattr(judge_output, 'reason', "")

            # Check eval retry: target→judge→fail→target loop
            # The target agent's after=[] won't include _judge_X, so scan all outputs.
            if critique is None:
                for output_key, output_val in outputs.items():
                    if output_key.startswith("_judge_") and hasattr(output_val, 'decision'):
                        if output_val.decision == "fail":
                            target_name = _judge_targets.get(output_key)
                            if target_name == agent_def.name:
                                critique = getattr(output_val, 'reason', "")
                                break

            # Build deps for this agent
            wid = builder_self.workflow_id or ""
            deps = AgentDeps(agent_name=agent_def.name, workflow_id=wid, node_id=agent_def.name)

            # Wire up reminder tracker (reads state lazily from deps)
            if todo_available:
                _reminder_tracker_holder[0] = TodoReminderTracker(deps)

            # Build the context (user message) — system prompt is already set via md_prompt
            context = micro_factory.build_node_prompt(
                inputs=state.get(STATE_INPUTS, {}),
                upstream_outputs=upstream_outputs,
                workflow_dir=workflow_dir,
                critique=critique,
            )

            # === Extension hook/middleware: before_node ===
            # Build a NodeCtx so middleware can mutate the prompt/messages.
            # messages starts empty here — extensions that need full history
            # (e.g. AutoCompact) accumulate it via on_llm_delta or maintain
            # their own state in ctx.metadata.
            ext_ctx: NodeCtx | None = None
            if bus and hasattr(bus, "run_middleware_chain"):
                ext_ctx = NodeCtx(
                    workflow=WorkflowCtx(
                        workflow_id=builder_self.workflow_id or "",
                        workflow_name=builder_self._workflow_name,
                        inputs=state.get(STATE_INPUTS, {}),
                    ),
                    node_id=agent_def.name,
                    agent_name=agent_def.name,
                    prompt=context,
                    messages=[
                        {"role": "system", "content": augmented_prompt},
                        {"role": "user", "content": context},
                    ],
                    upstream_outputs=upstream_outputs,
                    config=AgentConfig(
                        model=model,
                        retries=retries,
                        tools=final_tool_names,
                        tool_info=tool_info,
                        agent_md_path=md_path or None,
                        critique=critique,
                        result_type_name=result_type.__name__ if result_type else None,
                        system_prompt=augmented_prompt,
                    ),
                )
                mw_result = await bus.run_middleware_chain("before_node", ext_ctx)
                if isinstance(mw_result, RejectAction):
                    # Extension rejected the node — short-circuit as failure
                    duration_ms = int((time.time() - start_time) * 1000)
                    safe_emit(bus,"node.failed", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "error": f"Rejected by extension: {mw_result.reason}",
                        "error_type": "ExtensionRejectError",
                        "duration_ms": duration_ms,
                        "attempt": 1,
                        "will_retry": False,
                    })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: f"Rejected: {mw_result.reason}"},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }
                ext_ctx = mw_result
                context = ext_ctx.prompt  # pick up mutations
                await bus.run_hooks("on_node_start", ext_ctx)

            # Create the Pydantic AI agent with resolved tools
            pydantic_agent = micro_factory.create(
                name=agent_def.name,
                prompt=augmented_prompt,
                tools=final_tool_names,
                model=model,
                retries=retries,
                result_type=result_type,
                deps=deps,
            )

            # Run the Pydantic AI agent via LLMExecutor
            try:
                wid = builder_self.workflow_id or ""

                # Build interrupt callback: combines has_pending + consume
                def _check_interrupt(wf_id: str, ag_name: str) -> dict | None:
                    if not wf_id or not builder_self._has_pending_stop_regen(wf_id, ag_name):
                        return None
                    return builder_self._consume_stop_regen(wf_id)

                # Lazily import to avoid hard dep on bash tool at module level
                def _get_cancel_fn():
                    try:
                        from harness.tools.bash import cancel_process
                        return cancel_process
                    except ImportError:
                        return None

                executor = LLMExecutor(
                    pydantic_agent,
                    deps,
                    event_bus=bus,
                    workflow_id=wid,
                    node_id=agent_def.name,
                    agent_name=agent_def.name,
                    ext_ctx=ext_ctx,
                    check_interrupt=_check_interrupt,
                    cancel_fn=_get_cancel_fn(),
                    reminder_tracker=_reminder_tracker_holder[0],
                )
                exec_result = await executor.run(context)
                agent_run = exec_result.agent_run
                stop_regen = exec_result.stop_regen
                ttft_ms = exec_result.ttft_ms

                if stop_regen:
                    partial = stop_regen.get("partial_output", "") or ""
                    guidance = stop_regen.get("user_guidance", "") or ""

                    if guidance.strip():
                        # WS came with guidance → inline retry (existing behavior)
                        safe_emit(bus,"agent.text_delta", {
                            "workflow_id": wid,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "text": "\n\n--- [用户指导]: " + guidance + " ---\n\n",
                        })

                        parts = [context]
                        if partial.strip():
                            parts.append(f"[此前你的部分回复]:\n{partial}")
                        parts.append(f"[用户指导]: {guidance}")
                        parts.append("请基于上述部分回复与用户指导，重新生成完整回答。")
                        new_context = "\n\n".join(parts)

                        try:
                            retry_result = await executor.run(new_context)
                            agent_run = retry_result.agent_run
                        except Exception as retry_err:
                            logger.warning("[DIAG-RETRY] Retry failed: %s — using partial output", retry_err)
                            agent_run = None

                        safe_emit(bus,"workflow.resumed", {
                            "workflow_id": wid,
                            "node_id": agent_def.name,
                            "directive": guidance,
                        })
                    else:
                        # Pure stop (no guidance) → emit waiting event,
                        # await user guidance via asyncio.Event, then retry.
                        if bus:
                            safe_emit(bus,"workflow.waiting_for_guidance", {
                                "workflow_id": wid,
                                "node_id": agent_def.name,
                                "agent_name": agent_def.name,
                                "partial_output": partial,
                            })

                        guidance = await builder_self.await_guidance(timeout=300.0)

                        if guidance.strip():
                            # User provided guidance → inline retry
                            if bus:
                                safe_emit(bus,"agent.text_delta", {
                                    "workflow_id": wid,
                                    "node_id": agent_def.name,
                                    "agent_name": agent_def.name,
                                    "text": "\n\n--- [用户指导]: " + guidance + " ---\n\n",
                                })

                            parts = [context]
                            if partial.strip():
                                parts.append(f"[此前你的部分回复]:\n{partial}")
                            parts.append(f"[用户指导]: {guidance}")
                            parts.append("请基于上述部分回复与用户指导，重新生成完整回答。")
                            new_context = "\n\n".join(parts)

                            try:
                                retry_result = await executor.run(new_context)
                                agent_run = retry_result.agent_run
                            except Exception as retry_err:
                                logger.warning("[DIAG-RETRY] Retry failed: %s — using partial output", retry_err)
                                agent_run = None

                            if bus:
                                safe_emit(bus,"workflow.resumed", {
                                    "workflow_id": wid,
                                    "node_id": agent_def.name,
                                    "directive": guidance,
                                })
                        else:
                            # Timeout or empty — use partial output as result
                            output = partial or "(stopped)"
                            duration_ms = int((time.time() - start_time) * 1000)
                            io_data = {
                                "input_prompt": context,
                                "system_prompt": augmented_prompt,
                                "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                            }
                            builder_self.agent_io[agent_def.name] = io_data
                            _save_incremental(builder_self, bus)
                            if bus:
                                safe_emit(bus,"node.completed", {
                                    "workflow_id": builder_self.workflow_id,
                                    "node_id": agent_def.name,
                                    "agent_name": agent_def.name,
                                    "duration_ms": duration_ms,
                                    "status": "success",
                                    **io_data,
                                })
                            return {
                                STATE_OUTPUTS: {agent_def.name: output},
                                STATE_ERRORS: {},
                                STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                            }

                if agent_run is None or agent_run.result is None:
                    # Retry failed or produced no result — return partial output
                    # as success (skip validation gate) so downstream agents run normally
                    output = partial if stop_regen else "(agent produced no output)"
                    duration_ms = int((time.time() - start_time) * 1000)
                    io_data = {
                        "input_prompt": context,
                        "system_prompt": augmented_prompt,
                        "output_result": str(output),
                    }
                    builder_self.agent_io[agent_def.name] = io_data
                    _save_incremental(builder_self, bus)
                    if bus:
                        safe_emit(bus,"node.completed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "duration_ms": duration_ms,
                            "status": "success",
                            **io_data,
                        })
                    return {
                        STATE_OUTPUTS: {agent_def.name: output},
                        STATE_ERRORS: {},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }

                output = agent_run.result.output
                usage_obj = getattr(agent_run, 'usage', None)

                # === Output completeness validation gate ===
                validation_error = _validate_output(output, result_type)
                if validation_error:
                    duration_ms = int((time.time() - start_time) * 1000)
                    if bus:
                        safe_emit(bus,"node.failed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": validation_error,
                            "error_type": "OutputValidationError",
                            "duration_ms": duration_ms,
                            "attempt": 1,
                            "will_retry": False,
                        })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: validation_error},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }

                duration_ms = int((time.time() - start_time) * 1000)

                # Extract token usage (before hooks so plugins can read it)
                token_usage = None
                try:
                    token_usage = {
                        "input": usage_obj.input_tokens,
                        "output": usage_obj.output_tokens,
                        "total": usage_obj.total_tokens,
                    }
                except Exception:
                    pass

                # Calculate cost from token usage and model pricing
                cost_usd = None
                if token_usage:
                    model_name = model or ""
                    cost_usd = calculate_cost(token_usage["input"], token_usage["output"], model_name)

                # Write token_usage + cost_usd + duration_ms into ext_ctx.metadata so
                # hooks (e.g. PerfMetricsPlugin) can emit charts.
                if ext_ctx is not None:
                    ext_ctx.metadata.setdefault(agent_def.name, {})["duration_ms"] = duration_ms
                    if token_usage:
                        ext_ctx.metadata.setdefault(agent_def.name, {})["token_usage"] = token_usage
                    if cost_usd is not None:
                        ext_ctx.metadata.setdefault(agent_def.name, {})["cost_usd"] = cost_usd
                    if hasattr(executor, "tool_calls") and executor.tool_calls:
                        ext_ctx.metadata.setdefault(agent_def.name, {})["tool_calls"] = executor.tool_calls

                    # Seed score_history from prior state for judge nodes, so
                    # EvalChartPlugin can accumulate scores across retry iterations.
                    if agent_def.name.startswith("_judge_"):
                        prev_meta = state.get(STATE_METADATA, {}).get(agent_def.name, {})
                        if "score_history" in prev_meta:
                            ext_ctx.metadata.setdefault(agent_def.name, {})["score_history"] = list(prev_meta["score_history"])

                # === Extension hook/middleware: after_node ===
                # NOTE: RetryAction is recognized but not yet executed in P1.
                # The plan is to wire it into the LangGraph conditional-edge
                # mechanism (or a dedicated retry counter) in P3+. For now we
                # log it via ext.error so users see their judge fired.
                if ext_ctx is not None and hasattr(bus, "run_middleware_chain"):
                    mw_result = await bus.run_middleware_chain("after_node", (ext_ctx, output))
                    if isinstance(mw_result, RetryAction):
                        safe_emit(bus,"ext.warning", {
                            "extension": "engine",
                            "message": f"RetryAction received but not yet executed (P1 limitation): {mw_result.new_prompt!r}",
                        })
                    else:
                        _, output = mw_result  # tuple of (ctx, possibly-mutated output)
                    await bus.run_hooks("on_node_end", ext_ctx, output)

                node_meta = {"duration_ms": duration_ms}
                if token_usage:
                    node_meta["token_usage"] = token_usage
                if cost_usd is not None:
                    node_meta["cost_usd"] = cost_usd
                if ttft_ms is not None:
                    node_meta["ttft_ms"] = ttft_ms

                # Merge hook-written score_history back for judge nodes
                # (EvalChartPlugin accumulates via ctx.metadata[agent_name])
                if agent_def.name.startswith("_judge_") and ext_ctx is not None:
                    hook_meta = ext_ctx.metadata.get(agent_def.name, {})
                    if "score_history" in hook_meta:
                        node_meta["score_history"] = hook_meta["score_history"]

                # === Operating Envelope check ===
                envelope_cfg = builder_self.envelope
                if envelope_cfg:
                    wf_meta = state.get(STATE_METADATA, {})
                    acc_tokens = {"total": 0}
                    acc_steps = 0
                    for _name, _meta in wf_meta.items():
                        if isinstance(_meta, dict):
                            tu = _meta.get("token_usage", {})
                            acc_tokens["total"] += tu.get("total", 0)
                            tc = _meta.get("tool_calls", [])
                            acc_steps += len(tc) if isinstance(tc, list) else 0
                    # Add current node
                    if token_usage:
                        acc_tokens["total"] += token_usage.get("total", 0)
                    if hasattr(executor, "tool_calls"):
                        acc_steps += len(executor.tool_calls)

                    total_elapsed = int((time.time() - start_time) * 1000)
                    envelope_error = check_envelope(acc_tokens, acc_steps, total_elapsed, envelope_cfg)
                    if envelope_error:
                        if bus:
                            safe_emit(bus,"node.failed", {
                                "workflow_id": builder_self.workflow_id,
                                "node_id": agent_def.name,
                                "agent_name": agent_def.name,
                                "error": envelope_error,
                                "error_type": "EnvelopeExceeded",
                                "duration_ms": duration_ms,
                                "attempt": 1,
                                "will_retry": False,
                            })
                        return {
                            STATE_OUTPUTS: {},
                            STATE_ERRORS: {agent_def.name: envelope_error},
                            STATE_METADATA: {agent_def.name: node_meta},
                        }

                # Emit node.completed event + collect I/O for persistence
                io_data = {
                    "input_prompt": context,
                    "system_prompt": augmented_prompt,
                    "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                }
                if hasattr(executor, "tool_calls") and executor.tool_calls:
                    io_data["tool_calls"] = executor.tool_calls
                builder_self.agent_io[agent_def.name] = io_data
                # Incremental save: persist completed node data to disk
                _save_incremental(builder_self, bus)
                if bus:
                    event_payload = {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "duration_ms": duration_ms,
                        "status": "success",
                        **io_data,
                    }
                    if token_usage:
                        event_payload["token_usage"] = token_usage
                    if cost_usd is not None:
                        event_payload["cost_usd"] = cost_usd
                    if ttft_ms is not None:
                        event_payload["ttft_ms"] = ttft_ms
                    safe_emit(bus,"node.completed", event_payload)

                # Build iteration_counts update for conditional edges
                iter_update = {}
                if agent_def.has_conditional_edges:
                    iter_key = f"{agent_def.name}_loop"
                    # Determine decision from output
                    decision = _extract_decision(output)
                    if decision == "fail" and agent.on_fail is not None:
                        iter_update[iter_key] = state.get("iteration_counts", {}).get(iter_key, 0) + 1

                result_dict = {
                    STATE_OUTPUTS: {agent_def.name: output},
                    STATE_ERRORS: {},
                    STATE_METADATA: {agent_def.name: node_meta},
                }
                if iter_update:
                    result_dict["iteration_counts"] = iter_update

                return result_dict
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                error_type = type(e).__name__

                tool_calls_before_failure = None
                try:
                    if executor.tool_calls:
                        tool_calls_before_failure = [
                            {"tool_name": tc["tool_name"], "tool_args": tc.get("tool_args", {})}
                            for tc in executor.tool_calls
                        ]
                except NameError:
                    pass  # executor was never created (e.g. micro_factory.create failed)

                payload = {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": agent_def.name,
                    "agent_name": agent_def.name,
                    "error": str(e),
                    "error_type": error_type,
                    "duration_ms": duration_ms,
                    "attempt": 1,
                    "will_retry": False,
                }
                if tool_calls_before_failure:
                    payload["tool_calls_before_failure"] = tool_calls_before_failure

                if bus:
                    safe_emit(bus,"node.failed", payload)

                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {agent_def.name: str(e)},
                    STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                }

        return node_func

    def _make_passthrough_node_func(self, agent_def):
        """Create a no-op node function for _judge_X_passthrough nodes.

        Used in multi-downstream scenarios: judge routes to passthrough on
        pass, and downstream agents depend on the passthrough node. The
        judge's ReviewDecision is in outputs[_judge_X]; downstream agents
        get the target's output via judge_targets expansion.
        """
        async def passthrough_func(state: HarnessState) -> dict:
            # No-op: outputs already set by the judge node via passthrough.
            return {
                STATE_OUTPUTS: {},
                STATE_ERRORS: {},
                STATE_METADATA: {},
            }
        return passthrough_func


def _route_decision(state: HarnessState, agent_name: str) -> str:
    """Route based on the decision field in the agent's output."""
    outputs = state.get(STATE_OUTPUTS, {})
    output = outputs.get(agent_name)

    # If the node produced no output (error/failure), route to fail
    # rather than silently defaulting to pass.
    if output is None:
        return "fail"

    decision = _extract_decision(output)
    return decision if decision in ("pass", "fail") else "pass"


def _extract_decision(output: Any) -> str:
    """Extract decision from agent output, which may be a ReviewDecision model or a string."""
    if isinstance(output, ReviewDecision):
        return output.decision
    if isinstance(output, BaseModel):
        decision = getattr(output, "decision", None)
        if decision:
            return str(decision)
    if isinstance(output, str):
        lower = output.lower()
        if "fail" in lower:
            return "fail"
    return "pass"
