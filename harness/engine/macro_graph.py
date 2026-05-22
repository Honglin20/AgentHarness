from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from pydantic_graph import End

from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md, resolve_agent_md
from harness.extensions.eval.decisions import ReviewDecision as EvalReviewDecision
from harness.extensions.eval.summarizer import summarize_target
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.extensions.base import NodeCtx, RejectAction, RetryAction, WorkflowCtx
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolRegistry


# --- Stop & Regenerate signal management ---
_pending_stop_regen: dict[str, dict[str, str]] = {}  # workflow_id → {agent_name, partial_output, user_guidance}
_stop_regen_lock = asyncio.Lock()


async def request_stop_and_regenerate(
    workflow_id: str,
    agent_name: str,
    partial_output: str,
    user_guidance: str,
) -> None:
    """Called from WebSocket handler when user requests stop + regenerate.

    Aborts the agent's current streaming LLM call, then restarts the same agent
    with a new prompt built from (partial_output + user_guidance).
    """
    async with _stop_regen_lock:
        _pending_stop_regen[workflow_id] = {
            "agent_name": agent_name,
            "partial_output": partial_output,
            "user_guidance": user_guidance,
        }


def _has_pending_stop_regen(workflow_id: str, agent_name: str) -> bool:
    pending = _pending_stop_regen.get(workflow_id)
    return pending is not None and pending.get("agent_name") == agent_name


def _consume_stop_regen(workflow_id: str) -> dict[str, str] | None:
    return _pending_stop_regen.pop(workflow_id, None)


class ReviewDecision(BaseModel):
    """Default result_type for agents with conditional edges."""
    decision: Literal["pass", "fail"]
    reason: str


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
    ):
        self.tool_registry = tool_registry or ToolRegistry()
        self.event_bus = event_bus
        self.max_iterations = max_iterations
        self.workflow_id: str | None = None  # Set by runner before execution

        # Register event-bus-dependent tools when event_bus is available
        if event_bus and "ask_human" not in self.tool_registry.list_tools():
            from harness.tools.ask_human import AskHumanToolFactory
            self.tool_registry.register("ask_human", AskHumanToolFactory(event_bus=event_bus))

        self.micro_factory = MicroAgentFactory(tool_registry=self.tool_registry)

    def build(self, workflow) -> StateGraph:
        """Build a LangGraph StateGraph from a Workflow definition.

        Before building, apply any registered GraphMutator extensions so
        eval-judge nodes / sub-agent insertions take effect transparently.
        """
        # === Extension: apply GraphMutators ===
        if self.event_bus is not None and hasattr(self.event_bus, "get_mutators"):
            for mutator in self.event_bus.get_mutators():
                try:
                    workflow = mutator.mutate(workflow)
                except Exception as e:
                    self.event_bus.emit("ext.error", {
                        "extension": getattr(mutator, "name", "unknown"),
                        "phase": "mutate",
                        "error": str(e),
                    })

        agents = workflow.agents
        workflow_dir = workflow.workflow_dir

        # Parse all agent MD files via resolve_agent_md (private first, shared fallback)
        # Skip synthetic judge/passthrough nodes (no MD on disk)
        parsed_agents = {}
        for agent in agents:
            if getattr(agent, "_eval_target", None) is not None:
                continue  # _judge_X — no MD file
            if "_passthrough" in agent.name:
                continue  # passthrough node — no MD file
            md_path = resolve_agent_md(agent.name, workflow_dir)
            parsed = parse_agent_md(md_path)
            parsed_agents[agent.name] = parsed

        # Build execution order (static edges only)
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

        # Merge on_pass/on_fail from parsed MD into agent defs
        for agent in agents:
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
                node_func = self._make_node_func(agent_def, parsed, dep_map, workflow_dir)
            graph.add_node(agent_name, node_func)

        # Add edges from START to root nodes
        for agent_name in execution_order:
            if not dep_map[agent_name]:
                graph.add_edge(START, agent_name)

        # Add edges between dependent nodes
        for agent_name in execution_order:
            for dep in dep_map[agent_name]:
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
                router = (
                    lambda state, an=agent.name: _route_judgment(state, an)
                    if is_judge
                    else lambda state, an=agent.name: _route_decision(state, an)
                )

                graph.add_conditional_edges(
                    agent.name,
                    router,
                    targets,
                )

        # Add edges from leaf nodes to END (only if no conditional edges)
        downstream = set()
        for deps in dep_map.values():
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

        model = agent_def.model or parsed.model
        retries = parsed.retries
        result_type = agent_def.result_type

        # Auto-inject ReviewDecision if agent has conditional edges and no result_type
        if agent_def.has_conditional_edges and result_type is None:
            result_type = ReviewDecision

        return final_tool_names, model, retries, result_type

    def _make_node_func(self, agent_def, parsed, dep_map, workflow_dir):
        """Create an async LangGraph node function for an agent."""
        micro_factory = self.micro_factory
        bus = self.event_bus
        max_iterations = self.max_iterations
        builder_self = self  # Capture for workflow_id access
        final_tool_names, model, retries, result_type = self._resolve_agent_config(agent_def, parsed)
        upstream_names = dep_map[agent_def.name]

        async def node_func(state: HarnessState) -> dict:
            start_time = time.time()

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
                })

            # Gather upstream outputs
            upstream_outputs = {}
            outputs = state.get(STATE_OUTPUTS, {})
            for dep_name in upstream_names:
                if dep_name in outputs:
                    upstream_outputs[dep_name] = outputs[dep_name]

            # Extract critique from judge metadata (if this agent is retrying after a fail)
            critique = None
            metadata = state.get(STATE_METADATA, {})
            for dep_name in upstream_names:
                if dep_name.startswith("_judge_"):
                    judge_meta = metadata.get(dep_name, {})
                    judgment = judge_meta.get("judgment", {})
                    if judgment.get("decision") == "fail":
                        critique = judgment.get("reason", "")

            # Build deps for this agent
            deps = AgentDeps(agent_name=agent_def.name)

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
                        workflow_name="",
                        inputs=state.get(STATE_INPUTS, {}),
                    ),
                    node_id=agent_def.name,
                    agent_name=agent_def.name,
                    prompt=context,
                    messages=[{"role": "user", "content": context}],
                    upstream_outputs=upstream_outputs,
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
                prompt=parsed.prompt,
                tools=final_tool_names,
                model=model,
                retries=retries,
                result_type=result_type,
                deps=deps,
            )

            # Run the Pydantic AI agent (async)
            # Use iter() instead of run_stream() so that tool calls are fully executed.
            # run_stream() treats the first text output as "final result" and skips
            # subsequent tool calls (pydantic_ai end_strategy='early' default).
            try:
                stop_regen: dict[str, str] | None = None
                wid = builder_self.workflow_id if bus else None

                async def _run_agent(user_context: str):
                    """Run agent via iter() — executes tools fully, streams text + tool events."""
                    nonlocal stop_regen
                    async with pydantic_agent.iter(user_context, deps=deps) as agent_run:
                        node = agent_run.next_node
                        while not isinstance(node, End):
                            if pydantic_agent.is_model_request_node(node):
                                async with node.stream(agent_run.ctx) as stream:
                                    async for chunk in stream.stream_text(delta=True):
                                        if bus:
                                            bus.emit("agent.text_delta", {
                                                "workflow_id": wid,
                                                "node_id": agent_def.name,
                                                "agent_name": agent_def.name,
                                                "text": chunk,
                                            })
                                            if ext_ctx is not None and hasattr(bus, "run_hooks"):
                                                await bus.run_hooks("on_llm_delta", ext_ctx, chunk)
                                        if wid and _has_pending_stop_regen(wid, agent_def.name):
                                            stop_regen = _consume_stop_regen(wid)
                                            break
                                if stop_regen:
                                    break
                                node = await agent_run.next(node)

                            elif pydantic_agent.is_call_tools_node(node):
                                if bus:
                                    async with node.stream(agent_run.ctx) as stream:
                                        async for event in stream:
                                            ek = getattr(event, 'event_kind', '')
                                            if ek == 'function_tool_call':
                                                part = event.part
                                                bus.emit("agent.tool_call", {
                                                    "workflow_id": wid,
                                                    "node_id": agent_def.name,
                                                    "agent_name": agent_def.name,
                                                    "tool_name": part.tool_name,
                                                    "tool_args": part.args if hasattr(part, 'args') else {},
                                                })
                                            elif ek == 'function_tool_result':
                                                part = event.part
                                                bus.emit("agent.tool_result", {
                                                    "workflow_id": wid,
                                                    "node_id": agent_def.name,
                                                    "agent_name": agent_def.name,
                                                    "tool_name": part.tool_name,
                                                    "result": str(part.content) if hasattr(part, 'content') else "",
                                                })
                                                if ext_ctx is not None and hasattr(bus, "run_hooks"):
                                                    from harness.extensions.base import ToolCtx
                                                    tctx = ToolCtx(
                                                        node=ext_ctx,
                                                        tool_name=part.tool_name,
                                                        tool_args={},
                                                    )
                                                    await bus.run_hooks(
                                                        "on_tool_call",
                                                        tctx,
                                                        str(part.content) if hasattr(part, "content") else "",
                                                    )
                                else:
                                    async with node.stream(agent_run.ctx) as stream:
                                        async for _ in stream:
                                            pass
                                node = await agent_run.next(node)

                            else:
                                node = await agent_run.next(node)

                        return agent_run

                agent_run = await _run_agent(context)

                if stop_regen:
                    partial = stop_regen.get("partial_output", "") or ""
                    guidance = stop_regen.get("user_guidance", "") or ""
                    if not guidance.strip():
                        guidance = "请基于此重新整理思路。"

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

                    agent_run = await _run_agent(new_context)

                    bus.emit("workflow.resumed", {
                        "workflow_id": wid,
                        "node_id": agent_def.name,
                        "directive": guidance,
                    })
                    stop_regen = None

                output = agent_run.result.output
                usage_obj = agent_run.usage

                duration_ms = int((time.time() - start_time) * 1000)

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

                # Extract token usage
                token_usage = None
                try:
                    token_usage = {
                        "input": usage_obj.input_tokens,
                        "output": usage_obj.output_tokens,
                        "total": usage_obj.total_tokens,
                    }
                except Exception:
                    pass

                node_meta = {"duration_ms": duration_ms}
                if token_usage:
                    node_meta["token_usage"] = token_usage

                # Emit node.completed event
                if bus:
                    event_payload = {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "duration_ms": duration_ms,
                        "status": "success",
                    }
                    if token_usage:
                        event_payload["token_usage"] = token_usage
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
                duration_ms = int((time.time() - start_time) * 1000)

                if bus:
                    bus.emit("node.failed", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "error": str(e),
                        "duration_ms": duration_ms,
                        "attempt": 1,
                        "will_retry": False,
                    })

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

            if bus:
                bus.emit("node.started", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": judge_name,
                    "agent_name": judge_name,
                    "attempt": current_count + 1,
                })

            # 1. Lazy-summarize the target agent's MD
            try:
                target_md_path = resolve_agent_md(target_name, workflow_dir)
                target_md = target_md_path.read_text()
                summary = summarize_target(target_name, target_md, workflow_dir)
            except Exception:
                summary = "(summary unavailable)"

            # 2. Build judge system prompt (three-part)
            judge_prompt = (
                "你是一个评测员。以下是上一个 agent 的任务和任务结果,你来判断它是否完成。\n\n"
                f"## 上游 agent 的任务与红线(自动总结)\n{summary}\n\n"
                "## 评测标准\n"
                "- decision: 'pass' 或 'fail'\n"
                "- reason: 具体评语\n"
                "- score: 0.0-1.0 之间的浮点数(可选)\n"
            )

            # 3. Get target's output and run judge
            target_output = state.get(STATE_OUTPUTS, {}).get(target_name, "")
            user_msg = f"## Output from {target_name}\n{target_output}"

            try:
                from harness.engine.llm import LLMClient
                client = LLMClient(model=agent_def.model)
                judge_agent = client.agent(
                    system_prompt=judge_prompt,
                    output_type=EvalReviewDecision,
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

            # 4. Score history (chart emission handled by EvalChartPlugin)
            prev_meta = state.get(STATE_METADATA, {}).get(judge_name, {})
            score_history = list(prev_meta.get("score_history", []))
            if review.score is not None:
                score_history.append(review.score)

            # 5. Passthrough outputs + judgment in metadata
            iter_update = {}
            if review.decision == "fail" and agent_def.on_fail is not None:
                iter_update[iter_key] = current_count + 1

            if bus:
                bus.emit("node.completed", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": judge_name,
                    "agent_name": judge_name,
                    "duration_ms": duration_ms,
                    "status": "success",
                })

            result_dict = {
                STATE_OUTPUTS: {judge_name: target_output},  # passthrough
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
