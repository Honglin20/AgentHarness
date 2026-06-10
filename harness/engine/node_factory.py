"""Per-agent LangGraph node function construction.

Lifted out of ``MacroGraphBuilder`` for readability — the original
``_make_node_func`` was a ~550-line closure that drowned the surrounding
class. Behavior is byte-for-byte identical; the only change is that
``self`` became the explicit ``builder`` parameter so the closure captures
the same state.

Exports:
  - ``resolve_agent_config`` — merge MD + API agent definition
  - ``make_node_func`` — build a real agent node function
  - ``make_passthrough_node_func`` — build a no-op passthrough node function
"""
from __future__ import annotations

import json as _json
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.cost import calculate_cost
from harness.engine.schema_utils import ReviewDecision, strip_schema
from harness.engine.llm_executor import LLMExecutor
from harness.engine.llm_retry import execute_with_retry
from harness.engine.node_phases import (
    build_extension_context,
    build_node_failed_payload,
    build_node_started_payload,
    build_node_completed_payload,
    check_upstream_errors,
)
from harness.engine.state import HarnessState
from harness.engine.token_aggregator import TokenAggregator
from harness.extensions.base import NodeCtx, RejectAction, RetryAction
from harness.extensions.bus import safe_emit
from harness.extensions.envelope import check_envelope
from harness.tools.deps import AgentDeps
from harness.tools.todo_reminder import TodoReminderTracker

from harness.engine.incremental_save import _save_incremental
from harness.tools.todo import get_todo_state
from harness.engine.routing import _extract_decision

if TYPE_CHECKING:
    from harness.compiler.md_parser import ParsedAgent
    from harness.engine.builder import MacroGraphBuilder

logger = logging.getLogger(__name__)


def _collect_todo_state(builder: "MacroGraphBuilder", deps: AgentDeps, node_id: str) -> None:
    """Snapshot todo steps from deps onto the builder for later persistence."""
    ts = get_todo_state(deps)
    if ts and ts.steps:
        builder.todo_states[node_id] = [s.model_dump() for s in ts.steps]


def resolve_agent_config(
    builder: "MacroGraphBuilder",
    agent_def,
    parsed: "ParsedAgent",
) -> tuple[list[str] | None, str | None, int, type[BaseModel] | None]:
    """Merge tools, model, retries from API definition and MD file.

    Returns ``(final_tool_names, model, retries, result_type)``.
    """
    md_tools = parsed.tools
    api_tools = agent_def.tools or []
    if not md_tools and not api_tools:
        final_tool_names = None  # → resolve() loads all
    else:
        final_tool_names = md_tools + [t for t in api_tools if t not in md_tools]
        final_tool_names = builder.tool_registry.expand_globs(final_tool_names, strict=False)

    model = agent_def.model or parsed.model
    retries = parsed.retries
    result_type = agent_def.result_type

    # Auto-inject ReviewDecision if agent has conditional edges and no result_type
    if agent_def.has_conditional_edges and result_type is None:
        result_type = ReviewDecision

    return final_tool_names, model, retries, result_type


def make_node_func(
    builder: "MacroGraphBuilder",
    agent_def,
    parsed: "ParsedAgent",
    dep_map: dict[str, list[str] | None],
    workflow_dir,
    md_path: str = "",
    judge_targets: dict[str, str] | None = None,
):
    """Create an async LangGraph node function for an agent."""
    micro_factory = builder.micro_factory
    bus = builder.event_bus
    max_iterations = builder.max_iterations
    builder_self = builder  # Capture for workflow_id access
    final_tool_names, model, retries, result_type = resolve_agent_config(builder, agent_def, parsed)

    # Per-node reminder tracker (only when todo will be available to the agent).
    #
    # `todo` is FORCED-tier, so registry.resolve() injects it unless an
    # exclude list removes it. The check below keeps the original semantics
    # intact: when no whitelist is given (None) todo is always present;
    # when a whitelist is given, todo is present iff it's listed (FORCED
    # injection guarantees that). This also auto-adapts if exclude_tools
    # ever flows into this layer (then "todo" would be absent from
    # final_tool_names and the tracker correctly disables).
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
            schema = strip_schema(result_type.model_json_schema())
            augmented_prompt += (
                "\n\n## Output Format\n"
                "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n"
                "When finished, respond with JSON matching this schema (no markdown fences):\n"
                + _json.dumps(schema, indent=2, ensure_ascii=False)
            )
        except Exception:
            logger.warning(
                "Failed to inject result_type schema into prompt for %s",
                agent_def.name, exc_info=True,
            )

    async def node_func(state: HarnessState) -> dict:
        start_time = time.time()

        # Check iteration count for conditional edges
        if agent_def.has_conditional_edges:
            iter_key = f"{agent_def.name}_loop"
            current_count = state.get("iteration_counts", {}).get(iter_key, 0)
            if current_count >= max_iterations:
                if bus:
                    safe_emit(bus, "node.failed", build_node_failed_payload(
                        builder_self.workflow_id, agent_def.name, agent_def.name,
                        f"Max iterations ({max_iterations}) reached for conditional edge loop",
                        0, error_type="MaxIterationsError",
                    ))
                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {agent_def.name: f"Max iterations ({max_iterations}) exceeded"},
                    STATE_METADATA: {},
                    "iteration_counts": {iter_key: current_count},
                }

        # Emit node.started event (legacy WS path)
        if bus:
            safe_emit(bus, "node.started", build_node_started_payload(
                builder_self.workflow_id, agent_def.name, agent_def.name,
                model=model, tools=tool_info,
            ))

        # Check if any upstream dependency has failed — skip this node
        skip = check_upstream_errors(state, upstream_names)
        if skip is not None:
            if bus:
                safe_emit(bus, "node.failed", build_node_failed_payload(
                    builder_self.workflow_id, agent_def.name, agent_def.name,
                    f"Skipped: upstream '{skip.failed_dep}' failed",
                    0, error_type="UpstreamDependencyError",
                ))
            return {
                STATE_OUTPUTS: {},
                STATE_ERRORS: {agent_def.name: f"Skipped: upstream '{skip.failed_dep}' failed: {skip.error_info}"},
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
        # Per-node token aggregator — tracks primary agent + sub-agents
        node_token_agg = TokenAggregator()
        deps = AgentDeps(
            agent_name=agent_def.name,
            workflow_id=wid,
            node_id=agent_def.name,
            token_aggregator=node_token_agg,
        )

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
            ext_ctx = build_extension_context(
                workflow_id=builder_self.workflow_id or "",
                workflow_name=builder_self._workflow_name,
                node_id=agent_def.name,
                agent_name=agent_def.name,
                prompt=context,
                system_prompt=augmented_prompt,
                upstream_outputs=upstream_outputs,
                inputs=state.get(STATE_INPUTS, {}),
                config_model=model,
                config_retries=retries,
                config_tools=final_tool_names,
                config_tool_info=tool_info,
                config_agent_md_path=md_path or None,
                config_critique=critique,
                config_result_type_name=result_type.__name__ if result_type else None,
            )
            mw_result = await bus.run_middleware_chain("before_node", ext_ctx)
            if isinstance(mw_result, RejectAction):
                # Extension rejected the node — short-circuit as failure
                duration_ms = int((time.time() - start_time) * 1000)
                safe_emit(bus, "node.failed", build_node_failed_payload(
                    builder_self.workflow_id, agent_def.name, agent_def.name,
                    f"Rejected by extension: {mw_result.reason}",
                    duration_ms, error_type="ExtensionRejectError",
                ))
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
                    return None  # intentional silent fallback — bash tool is optional

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
                token_aggregator=node_token_agg,
                request_limit=getattr(builder_self, "request_limit", None),
            )
            # Wrap executor.run with the LLM retry policy. On each failed
            # attempt, execute_with_retry emits agent.retry_attempted (and the
            # final agent.failed_with_classified_reason if exhausted). The
            # run_fn lambda constructs a fresh iter() per attempt — Pydantic AI
            # doesn't support single-step replay (see llm_retry.py docstring).
            exec_result = await execute_with_retry(
                lambda: executor.run(context),
                bus=bus,
                workflow_id=wid,
                node_id=agent_def.name,
                agent_name=agent_def.name,
            )
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
                        _collect_todo_state(builder_self, deps, agent_def.name)
                        _save_incremental(builder_self, bus)
                        if bus:
                            safe_emit(bus, "node.completed", build_node_completed_payload(
                                builder_self.workflow_id, agent_def.name, agent_def.name,
                                output, duration_ms, io_data=io_data,
                            ))
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
                _collect_todo_state(builder_self, deps, agent_def.name)
                _save_incremental(builder_self, bus)
                if bus:
                    safe_emit(bus, "node.completed", build_node_completed_payload(
                        builder_self.workflow_id, agent_def.name, agent_def.name,
                        output, duration_ms, io_data=io_data,
                    ))
                return {
                    STATE_OUTPUTS: {agent_def.name: output},
                    STATE_ERRORS: {},
                    STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                }

            output = agent_run.result.output
            usage_obj = getattr(agent_run, 'usage', None)

            # Record usage into the per-node aggregator (primary agent)
            executor.record_usage(usage_obj)

            # Schema validation is now handled by pydantic-ai's output_type
            # mechanism + step_gate output_validator (injected in micro_agent.py).
            # Both schema errors and step-gate violations raise ModelRetry,
            # which pydantic-ai converts into a continued iter() with the retry
            # prompt appended to message_history. After output_retries (budget=1)
            # exhausted, pydantic-ai raises UnexpectedModelBehavior — caught by
            # the except block below, which emits node.failed with the original
            # error preserved. See ADR 2026-06-10-todo-step-gate-adr.md.

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
                logger.debug(
                    "Failed to extract token usage for %s", agent_def.name, exc_info=True,
                )

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

            # Include per-agent token breakdown (primary + sub-agents)
            token_breakdown = node_token_agg.get_breakdown()
            if token_breakdown:
                node_meta["token_breakdown"] = token_breakdown

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
                        safe_emit(bus, "node.failed", build_node_failed_payload(
                            builder_self.workflow_id, agent_def.name, agent_def.name,
                            envelope_error, duration_ms,
                            error_type="EnvelopeExceeded",
                        ))
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
            _collect_todo_state(builder_self, deps, agent_def.name)
            # Incremental save: persist completed node data to disk
            _save_incremental(builder_self, bus)
            if bus:
                safe_emit(bus, "node.completed", build_node_completed_payload(
                    builder_self.workflow_id, agent_def.name, agent_def.name,
                    output, duration_ms, token_usage=token_usage,
                    cost_usd=cost_usd, ttft_ms=ttft_ms, io_data=io_data,
                    token_breakdown=token_breakdown or None,
                ))

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
            _collect_todo_state(builder_self, deps, agent_def.name)
            # pydantic-ai raises UnexpectedModelBehavior when output retry
            # budget is exhausted (covers step_gate ModelRetry retries +
            # schema validation failures). Translate to a more semantically
            # meaningful error_type so frontend can classify display.
            if type(e).__name__ == "UnexpectedModelBehavior":
                error_type = "OutputValidationRetryExhausted"
            else:
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

            extra = {}
            if tool_calls_before_failure:
                extra["tool_calls_before_failure"] = tool_calls_before_failure

            if bus:
                safe_emit(bus, "node.failed", build_node_failed_payload(
                    builder_self.workflow_id, agent_def.name, agent_def.name,
                    str(e), duration_ms, error_type=error_type, extra=extra or None,
                ))

            return {
                STATE_OUTPUTS: {},
                STATE_ERRORS: {agent_def.name: str(e)},
                STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
            }

    return node_func


def make_passthrough_node_func(agent_def):
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
