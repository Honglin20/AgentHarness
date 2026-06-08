"""Pure helper functions extracted from MacroGraphBuilder._make_node_func.

These functions are stateless and testable in isolation. They build event
payloads, check upstream error conditions, and construct extension contexts
without depending on any closure-captured mutable state.

The nodeFunc closure in macro_graph.py calls these helpers, keeping the
closure itself focused on orchestration (LLM execution, retry, interrupts).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from harness.extensions.base import AgentConfig, NodeCtx, WorkflowCtx


# ---------------------------------------------------------------------------
# Upstream error checking
# ---------------------------------------------------------------------------

@dataclass
class NodeSkipResult:
    """Returned when an upstream dependency has failed, causing this node to be skipped."""
    failed_dep: str
    error_info: Any  # str or dict — whatever was stored in state["errors"]


def check_upstream_errors(state: dict, upstream_deps: list[str]) -> NodeSkipResult | None:
    """Check if any upstream dependency has an error in the state.

    Pure function — reads only from the provided state dict.

    Returns a NodeSkipResult naming the first failed dependency,
    or None if all deps are clean.
    """
    errors = state.get("errors", {})
    for dep_name in upstream_deps:
        if dep_name in errors:
            return NodeSkipResult(failed_dep=dep_name, error_info=errors[dep_name])
    return None


# ---------------------------------------------------------------------------
# Event payload builders
# ---------------------------------------------------------------------------

def build_node_started_payload(
    workflow_id: str | None,
    node_id: str,
    agent_name: str,
    *,
    model: str | None = None,
    tools: Any = None,
    attempt: int = 1,
) -> dict:
    """Build the payload dict for a ``node.started`` event.

    The caller (nodeFunc) passes this to ``safe_emit(bus, "node.started", ...)``.
    """
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "attempt": attempt,
        "model": model,
        "ts": int(time.time() * 1000),
    }
    if tools is not None:
        payload["tools"] = tools
    return payload


def build_node_completed_payload(
    workflow_id: str | None,
    node_id: str,
    agent_name: str,
    output: Any,
    duration_ms: float,
    token_usage: dict | None = None,
    *,
    cost_usd: float | None = None,
    ttft_ms: float | None = None,
    io_data: dict | None = None,
    token_breakdown: dict | None = None,
) -> dict:
    """Build the payload dict for a ``node.completed`` event.

    Merges io_data (input_prompt, system_prompt, output_result) and optional
    token_usage / cost / ttft metrics into a single event payload.
    """
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "duration_ms": duration_ms,
        "status": "success",
    }
    if io_data:
        payload.update(io_data)
    if token_usage:
        payload["token_usage"] = token_usage
    if cost_usd is not None:
        payload["cost_usd"] = cost_usd
    if ttft_ms is not None:
        payload["ttft_ms"] = ttft_ms
    if token_breakdown:
        payload["token_breakdown"] = token_breakdown
    return payload


def build_node_failed_payload(
    workflow_id: str | None,
    node_id: str,
    agent_name: str,
    error: str,
    duration_ms: float,
    *,
    error_type: str | None = None,
    attempt: int = 1,
    will_retry: bool = False,
    extra: dict | None = None,
) -> dict:
    """Build the payload dict for a ``node.failed`` event."""
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "error": error,
        "error_type": error_type or "Error",
        "duration_ms": duration_ms,
        "attempt": attempt,
        "will_retry": will_retry,
    }
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Extension context builder
# ---------------------------------------------------------------------------

def build_extension_context(
    *,
    workflow_id: str,
    workflow_name: str,
    node_id: str,
    agent_name: str,
    prompt: str,
    system_prompt: str,
    upstream_outputs: dict[str, Any],
    inputs: dict[str, Any] | None = None,
    config_model: str | None = None,
    config_retries: int = 3,
    config_tools: list[str] | None = None,
    config_tool_info: Any = None,
    config_agent_md_path: str | None = None,
    config_critique: str | None = None,
    config_result_type_name: str | None = None,
) -> NodeCtx:
    """Build a ``NodeCtx`` for the extension middleware/hook system.

    This is a pure constructor — no side effects. The caller passes the
    resulting NodeCtx into ``bus.run_middleware_chain("before_node", ...)``.
    """
    return NodeCtx(
        workflow=WorkflowCtx(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            inputs=inputs or {},
        ),
        node_id=node_id,
        agent_name=agent_name,
        prompt=prompt,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        upstream_outputs=upstream_outputs,
        config=AgentConfig(
            model=config_model,
            retries=config_retries,
            tools=config_tools or [],
            tool_info=config_tool_info or [],
            agent_md_path=config_agent_md_path,
            critique=config_critique,
            result_type_name=config_result_type_name,
            system_prompt=system_prompt,
        ),
    )
