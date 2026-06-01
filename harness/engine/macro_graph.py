from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, ValidationError
from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md, resolve_agent_md
from harness.extensions.eval.decisions import EvalJudge
from harness.extensions.eval.summarizer import summarize_target
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.extensions.base import AgentConfig, NodeCtx, RejectAction, RetryAction, WorkflowCtx
from harness.engine.llm_executor import LLMExecutor
from harness.extensions.envelope import check_envelope
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.cost import calculate_cost
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolRegistry


# --- Stop & Regenerate signal management ---
def _get_stop_regen_ttl() -> int:
    """Read TTL from env, defaulting to 60s."""
    try:
        return int(os.environ.get("HARNESS_STOP_REGEN_TTL", "60"))
    except ValueError:
        return 60


# Registry of active builders keyed by workflow_id, used by the module-level
# request_stop_and_regenerate shim to forward to the correct builder instance.
_active_builders: dict[str, "MacroGraphBuilder"] = {}  # populated after class def


async def request_stop_and_regenerate(
    workflow_id: str,
    agent_name: str,
    partial_output: str,
    user_guidance: str,
) -> None:
    """Module-level shim: forwards to the active builder's instance method.

    Kept for backward compatibility with ws_handler imports.
    """
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        await builder.request_stop_and_regenerate(
            agent_name, partial_output, user_guidance,
        )


def clear_stop_regen(workflow_id: str) -> None:
    """Clear any pending stop-and-regenerate signal for a workflow.

    Called when a workflow is cancelled/paused to prevent stale signals
    from triggering immediate interrupts on resume.
    """
    builder = _active_builders.get(workflow_id)
    if builder is not None:
        builder._pending_stop_regen.pop(workflow_id, None)


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

        # Stop-and-regenerate signal state (instance-scoped)
        self._pending_stop_regen: dict[str, dict[str, str | float]] = {}
        self._stop_regen_lock = asyncio.Lock()

        # Interrupt intent: persists across node re-execution after LangGraph interrupt()
        self._interrupted_agents: dict[str, dict[str, Any]] = {}

        # Register event-bus-dependent tools when event_bus is available
        if event_bus and "ask_user" not in self.tool_registry.list_tools():
            from harness.tools.ask_user import AskUserToolFactory
            self.tool_registry.register("ask_user", AskUserToolFactory(event_bus=event_bus))

        self.micro_factory = MicroAgentFactory(tool_registry=self.tool_registry)

    # ---- Stop & Regenerate instance methods ----

    async def request_stop_and_regenerate(
        self,
        agent_name: str,
        partial_output: str,
        user_guidance: str,
    ) -> None:
        """Request stop + regenerate for a specific agent in this workflow."""
        wid = self.workflow_id or ""
        async with self._stop_regen_lock:
            self._pending_stop_regen[wid] = {
                "agent_name": agent_name,
                "partial_output": partial_output,
                "user_guidance": user_guidance,
                "_ts": time.time(),
            }

    def store_interrupt_intent(self, agent_name: str, data: dict[str, Any]) -> None:
        """Store interrupt intent for a node so it can resume correctly after re-execution."""
        self._interrupted_agents[agent_name] = data

    def consume_interrupt_intent(self, agent_name: str) -> dict[str, Any] | None:
        """Consume and return interrupt intent, or None if not present."""
        return self._interrupted_agents.pop(agent_name, None)

    def _has_pending_stop_regen(self, workflow_id: str, agent_name: str) -> bool:
        pending = self._pending_stop_regen.get(workflow_id)
        if pending is None:
            return False
        if time.time() - pending.get("_ts", 0) > _get_stop_regen_ttl():
            self._pending_stop_regen.pop(workflow_id, None)
            return False
        return pending.get("agent_name") == agent_name

    def _consume_stop_regen(self, workflow_id: str) -> dict[str, str] | None:
        return self._pending_stop_regen.pop(workflow_id, None)

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
        # Skip synthetic judge/passthrough nodes (no MD on disk)
        parsed_agents = {}
        agent_md_paths = {}
        for agent in agents:
            if getattr(agent, "_eval_target", None) is not None:
                continue  # _judge_X — no MD file
            if "_passthrough" in agent.name:
                continue  # passthrough node — no MD file
            md_path = resolve_agent_md(agent.name, workflow_dir)
            agent_md_paths[agent.name] = str(md_path)
            parsed = parse_agent_md(md_path)
            parsed_agents[agent.name] = parsed

        # Build execution order (static edges only)
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

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
            eval_target = getattr(agent_def, "_eval_target", None)
            is_passthrough = "_passthrough" in agent_name

            if eval_target is not None:
                # Judge node — special handler
                node_func = self._make_judge_node_func(agent_def, eval_target, dep_map, workflow_dir)
            elif is_passthrough:
                node_func = self._make_passthrough_node_func(agent_def)
            else:
                parsed = parsed_agents[agent_name]
                node_func = self._make_node_func(agent_def, parsed, dep_map, workflow_dir, agent_md_paths.get(agent_name, ""))
            graph.add_node(agent_name, node_func)

        # Collect conditional edge targets — these are activated by routing,
        # not by START, even if they have no `after` dependency.
        # Exception: a node that is a root (no deps) should still get START edge
        # even if it's a conditional target (for retry/loop scenarios).
        conditional_targets = set()
        # Track agents with after=None (only trigger via conditional edges)
        conditional_only_nodes = set()
        for agent in agents:
            if agent.after is None:
                conditional_only_nodes.add(agent.name)
            if agent.has_conditional_edges:
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
        for agent_name in execution_order:
            deps = dep_map[agent_name] or []
            for dep in deps:
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

                # Judge nodes route from metadata, normal nodes from outputs
                is_judge = getattr(agent, "_eval_target", None) is not None
                if is_judge:
                    router = lambda state, an=agent.name: _route_judgment(state, an)
                else:
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
            final_tool_names = self.tool_registry.expand_globs(final_tool_names)

        model = agent_def.model or parsed.model
        retries = parsed.retries
        result_type = agent_def.result_type

        # Auto-inject ReviewDecision if agent has conditional edges and no result_type
        if agent_def.has_conditional_edges and result_type is None:
            result_type = ReviewDecision

        return final_tool_names, model, retries, result_type

    def _make_node_func(self, agent_def, parsed, dep_map, workflow_dir, md_path=""):
        """Create an async LangGraph node function for an agent."""
        micro_factory = self.micro_factory
        bus = self.event_bus
        max_iterations = self.max_iterations
        builder_self = self  # Capture for workflow_id access
        final_tool_names, model, retries, result_type = self._resolve_agent_config(agent_def, parsed)
        tool_info = micro_factory.tool_registry.get_tool_info(final_tool_names)
        upstream_names = dep_map[agent_def.name] or []

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

            # === CASE A: Resume from LangGraph interrupt ===
            # On resume, the node re-executes from scratch. Check if we stored
            # interrupt intent for this agent and retrieve it.
            intent = builder_self.consume_interrupt_intent(agent_def.name)

            if intent is not None:
                from langgraph.types import interrupt as lg_interrupt
                # interrupt() returns the resume value (user guidance) on re-execution
                guidance = lg_interrupt({
                    "agent_name": agent_def.name,
                    "partial_output": intent.get("partial_output", ""),
                    "reason": "stop_and_regenerate",
                })

                # Rebuild upstream outputs and deps from state
                upstream_outputs = {}
                outputs = state.get(STATE_OUTPUTS, {})
                for dep_name in upstream_names:
                    if dep_name in outputs:
                        upstream_outputs[dep_name] = outputs[dep_name]

                wid = builder_self.workflow_id or ""
                deps = AgentDeps(agent_name=agent_def.name, workflow_id=wid, node_id=agent_def.name)

                # Rebuild context for resume
                resume_context = micro_factory.build_node_prompt(
                    inputs=state.get(STATE_INPUTS, {}),
                    upstream_outputs=upstream_outputs,
                    workflow_dir=workflow_dir,
                    critique=None,
                )

                if guidance:
                    # Augment context with partial output + user guidance
                    partial = intent.get("partial_output", "")
                    if bus:
                        bus.emit("agent.text_delta", {
                            "workflow_id": wid,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "text": "\n\n--- [用户指导]: " + guidance + " ---\n\n",
                        })
                    parts = [resume_context]
                    if partial.strip():
                        parts.append(f"[此前你的部分回复]:\n{partial}")
                    parts.append(f"[用户指导]: {guidance}")
                    parts.append("请基于上述部分回复与用户指导，重新生成完整回答。")
                    resume_context = "\n\n".join(parts)

                # Emit node.started for the resume run
                if bus:
                    bus.emit("node.started", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "attempt": 1,
                        "tools": tool_info,
                        "model": model,
                    })

                # Re-create executor for resume
                pydantic_agent_resume = micro_factory.create(
                    name=agent_def.name,
                    prompt=intent.get("system_prompt", augmented_prompt),
                    tools=final_tool_names,
                    model=model,
                    retries=retries,
                    result_type=result_type,
                    deps=deps,
                )

                executor = LLMExecutor(
                    pydantic_agent_resume,
                    deps,
                    event_bus=bus,
                    workflow_id=wid,
                    node_id=agent_def.name,
                    agent_name=agent_def.name,
                    ext_ctx=None,
                    check_interrupt=None,
                    cancel_fn=None,
                )

                if guidance:
                    exec_result = await executor.run(resume_context)
                    agent_run = exec_result.agent_run
                    output = agent_run.result.output

                    if bus:
                        bus.emit("workflow.resumed", {
                            "workflow_id": wid,
                            "node_id": agent_def.name,
                            "directive": guidance,
                        })
                else:
                    # No guidance: use partial output, node completes
                    output = intent.get("partial_output", "") or "(stopped)"

                duration_ms = int((time.time() - start_time) * 1000)
                node_meta = {"duration_ms": duration_ms}

                # Emit node.completed
                io_data = {
                    "input_prompt": resume_context,
                    "system_prompt": intent.get("system_prompt", augmented_prompt),
                    "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
                }
                builder_self.agent_io[agent_def.name] = io_data
                _save_incremental(builder_self, bus)
                if bus:
                    bus.emit("node.completed", {
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
                    STATE_METADATA: {agent_def.name: node_meta},
                }

            # === Normal first execution (existing code) ===

            # Check iteration count for conditional edges
            if agent_def.has_conditional_edges:
                iter_key = f"{agent_def.name}_loop"
                current_count = state.get("iteration_counts", {}).get(iter_key, 0)
                if current_count >= max_iterations:
                    if bus:
                        bus.emit("node.failed", {
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
                bus.emit("node.started", {
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
                        bus.emit("node.failed", {
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

            # Extract critique from judge metadata (if this agent is retrying after a fail)
            critique = None
            metadata = state.get(STATE_METADATA, {})

            # Check upstream deps (normal case: downstream of a judge)
            for dep_name in upstream_names:
                if dep_name.startswith("_judge_"):
                    judge_meta = metadata.get(dep_name, {})
                    judgment = judge_meta.get("judgment", {})
                    if judgment.get("decision") == "fail":
                        critique = judgment.get("reason", "")

            # Check eval retry: target→judge→fail→target loop
            # The target agent's after=[] won't include _judge_X, so scan metadata.
            if critique is None:
                for meta_key, meta_val in metadata.items():
                    if meta_key.startswith("_judge_") and isinstance(meta_val, dict):
                        if meta_val.get("target") == agent_def.name:
                            judgment = meta_val.get("judgment", {})
                            if judgment.get("decision") == "fail":
                                critique = judgment.get("reason", "")
                                break

            # Build deps for this agent
            wid = builder_self.workflow_id or ""
            deps = AgentDeps(agent_name=agent_def.name, workflow_id=wid, node_id=agent_def.name)

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
                    bus.emit("node.failed", {
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
                        bus.emit("agent.text_delta", {
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

                        retry_result = await executor.run(new_context)
                        agent_run = retry_result.agent_run
                        stop_regen = None

                        bus.emit("workflow.resumed", {
                            "workflow_id": wid,
                            "node_id": agent_def.name,
                            "directive": guidance,
                        })
                        stop_regen = None
                    else:
                        # Pure stop → store intent and interrupt the graph.
                        # The graph will pause, and on resume the CASE A block
                        # at the top of this function will handle re-execution.
                        builder_self.store_interrupt_intent(agent_def.name, {
                            "original_context": context,
                            "partial_output": partial,
                            "system_prompt": augmented_prompt,
                        })
                        from langgraph.types import interrupt as lg_interrupt
                        lg_interrupt({
                            "agent_name": agent_def.name,
                            "partial_output": partial,
                            "reason": "stop_and_regenerate",
                        })
                        # UNREACHABLE — interrupt() raises GraphInterrupt

                output = agent_run.result.output
                usage_obj = agent_run.usage

                # === Output completeness validation gate ===
                validation_error = _validate_output(output, result_type)
                if validation_error:
                    duration_ms = int((time.time() - start_time) * 1000)
                    if bus:
                        bus.emit("node.failed", {
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

                # === Extension hook/middleware: after_node ===
                # NOTE: RetryAction is recognized but not yet executed in P1.
                # The plan is to wire it into the LangGraph conditional-edge
                # mechanism (or a dedicated retry counter) in P3+. For now we
                # log it via ext.error so users see their judge fired.
                if ext_ctx is not None and hasattr(bus, "run_middleware_chain"):
                    mw_result = await bus.run_middleware_chain("after_node", (ext_ctx, output))
                    if isinstance(mw_result, RetryAction):
                        bus.emit("ext.warning", {
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
                            bus.emit("node.failed", {
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
                    bus.emit("node.completed", event_payload)

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
                # Let LangGraph interrupt signals propagate — they must reach
                # the graph runtime to pause execution, not be swallowed here.
                from langgraph.errors import GraphInterrupt
                if isinstance(e, GraphInterrupt):
                    raise

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
                    bus.emit("node.failed", payload)

                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {agent_def.name: str(e)},
                    STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                }

        return node_func

    def _make_judge_node_func(self, agent_def, target_name, dep_map, workflow_dir):
        """Create an async LangGraph node function for an _judge_X node.

        The judge evaluates the target agent's output and returns a ReviewDecision.
        On pass: outputs[judge_name] = outputs[target_name] (passthrough).
        Judgment is stored in metadata, not outputs, so the routing fn can read it.
        """
        bus = self.event_bus
        builder_self = self
        max_iterations = self.max_iterations

        async def judge_func(state: HarnessState) -> dict:
            start_time = time.time()
            judge_name = agent_def.name

            # Check iteration count for loop termination
            iter_key = f"{judge_name}_loop"
            current_count = state.get("iteration_counts", {}).get(iter_key, 0)
            if current_count >= max_iterations:
                if bus:
                    bus.emit("node.failed", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": judge_name,
                        "agent_name": judge_name,
                        "error": f"Max eval retries ({max_iterations}) reached",
                        "duration_ms": 0,
                        "attempt": current_count + 1,
                        "will_retry": False,
                    })
                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {judge_name: f"Max eval retries ({max_iterations}) exceeded"},
                    STATE_METADATA: {},
                    "iteration_counts": {iter_key: current_count},
                }

            # 1. Read judge system prompt from MD file (user-editable)
            judge_prompt = _default_judge_prompt(target_name)
            try:
                md_path = resolve_agent_md(judge_name, workflow_dir)
                parsed = parse_agent_md(md_path)
                judge_prompt = parsed.prompt
            except Exception:
                pass  # fallback to default

            # 2. Lazy-summarize the target agent's MD (injected as context, not in system prompt)
            summary = "(summary unavailable)"
            try:
                target_md_path = resolve_agent_md(target_name, workflow_dir)
                target_md = target_md_path.read_text()
                summary = summarize_target(target_name, target_md, workflow_dir)
            except Exception:
                pass

            # 3. Build user message: target summary + target output
            raw_output = state.get(STATE_OUTPUTS, {}).get(target_name, "")
            target_output = raw_output.model_dump() if isinstance(raw_output, BaseModel) else raw_output
            import json as _json
            output_text = _json.dumps(target_output, ensure_ascii=False, indent=2) if isinstance(target_output, dict) else str(target_output)
            user_msg = (
                f"## 上游 agent「{target_name}」的任务与红线\n{summary}\n\n"
                f"## Output from {target_name}\n{output_text}"
            )

            # Build NodeCtx for hooks (same as regular node)
            judge_ext_ctx = None
            if bus and hasattr(bus, "run_hooks"):
                judge_ext_ctx = NodeCtx(
                    workflow=WorkflowCtx(
                        workflow_id=builder_self.workflow_id or "",
                        workflow_name=builder_self._workflow_name,
                        inputs=state.get(STATE_INPUTS, {}),
                    ),
                    node_id=judge_name,
                    agent_name=judge_name,
                    prompt=user_msg,
                    messages=[
                        {"role": "system", "content": judge_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    upstream_outputs={target_name: target_output},
                    config=AgentConfig(
                        model=agent_def.model,
                        retries=1,
                        tools=[],
                        tool_info=[],
                        result_type_name="ReviewDecision",
                    ),
                )
                hook_result = bus.run_hooks("on_node_start", judge_ext_ctx)
                if hook_result is not None and hasattr(hook_result, "__await__"):
                    await hook_result

            if bus:
                # Judge has no external tools — resolve empty list
                bus.emit("node.started", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": judge_name,
                    "agent_name": judge_name,
                    "attempt": current_count + 1,
                    "tools": [],
                    "model": agent_def.model,
                })

            try:
                from harness.engine.llm import LLMClient
                client = LLMClient(model=agent_def.model)
                judge_agent = client.agent(
                    system_prompt=judge_prompt,
                    output_type=ReviewDecision,
                    retries=1,
                    tools=[],
                    deps_type=AgentDeps,
                )
                result = await judge_agent.run(user_msg, deps=AgentDeps(agent_name=judge_name))
                review = result.output
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                if bus:
                    bus.emit("node.failed", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": judge_name,
                        "agent_name": judge_name,
                        "error": str(e),
                        "duration_ms": duration_ms,
                        "attempt": current_count + 1,
                        "will_retry": False,
                    })
                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {judge_name: str(e)},
                    STATE_METADATA: {judge_name: {"duration_ms": duration_ms}},
                }

            duration_ms = int((time.time() - start_time) * 1000)

            # 4. Score history + chart emission
            prev_meta = state.get(STATE_METADATA, {}).get(judge_name, {})
            score_history = list(prev_meta.get("score_history", []))
            if review.score is not None:
                score_history.append(review.score)
                # Emit chart directly (judge nodes bypass the hook system)
                if bus:
                    bus.emit("chart.render", {
                        "node_id": judge_name,
                        "chart_type": "line",
                        "data": [{"iteration": i + 1, "score": s} for i, s in enumerate(score_history)],
                        "x": "iteration",
                        "y": "score",
                        "label": "Eval Scores",
                        "title": f"{target_name} quality",
                        "category": "analysis",
                    })

            # 5. Passthrough outputs + judgment in metadata
            iter_update = {}
            if review.decision == "fail" and agent_def.on_fail is not None:
                iter_update[iter_key] = current_count + 1

            # Hook: on_node_end so plugins (ConsoleOutput etc.) can print the review
            if judge_ext_ctx is not None and bus and hasattr(bus, "run_hooks"):
                judge_ext_ctx.metadata.setdefault(judge_name, {})["duration_ms"] = duration_ms
                hook_result = bus.run_hooks("on_node_end", judge_ext_ctx, review)
                if hook_result is not None and hasattr(hook_result, "__await__"):
                    await hook_result

            if bus:
                bus.emit("node.completed", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": judge_name,
                    "agent_name": judge_name,
                    "duration_ms": duration_ms,
                    "status": "success",
                })

            # Passthrough: outputs unchanged (judgment stored in metadata only).
            # Downstream consumers read judgment from metadata, not outputs.
            result_dict = {
                STATE_OUTPUTS: {judge_name: target_output},
                STATE_ERRORS: {},
                STATE_METADATA: {judge_name: {
                    "duration_ms": duration_ms,
                    "judgment": review.model_dump(),
                    "score_history": score_history,
                    "target": target_name,
                }},
            }
            if iter_update:
                result_dict["iteration_counts"] = iter_update

            return result_dict

        return judge_func

    def _make_passthrough_node_func(self, agent_def):
        """Create a no-op node function for _judge_X_passthrough nodes.

        It just passes the state through — the real output is already in
        outputs[_judge_X] (the target's original output, passthrough'd).
        """
        async def passthrough_func(state: HarnessState) -> dict:
            # No-op: outputs already set by the judge node via passthrough.
            return {
                STATE_OUTPUTS: {},
                STATE_ERRORS: {},
                STATE_METADATA: {},
            }
        return passthrough_func


def _default_judge_prompt(target_name: str) -> str:
    """Fallback judge prompt when no MD file is found."""
    return (
        "你是一个评测员。你的任务是评估上游 agent 的输出质量。\n\n"
        "## 评测标准\n"
        "- decision: 'pass' 或 'fail'\n"
        "- reason: 具体评语\n"
        "- score: 0.0-1.0 之间的浮点数(可选)\n"
    )


def _route_judgment(state: HarnessState, judge_name: str) -> str:
    """Route based on the judgment stored in metadata (not outputs).

    Judge nodes store their ReviewDecision in metadata[judge_name].judgment,
    so the routing fn must read from there rather than from outputs.
    """
    metadata = state.get(STATE_METADATA, {})
    judgment = metadata.get(judge_name, {}).get("judgment", {})
    decision = judgment.get("decision", "pass")
    return decision if decision in ("pass", "fail") else "pass"


def _route_decision(state: HarnessState, agent_name: str) -> str:
    """Route based on the decision field in the agent's output."""
    outputs = state.get(STATE_OUTPUTS, {})
    output = outputs.get(agent_name)

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
