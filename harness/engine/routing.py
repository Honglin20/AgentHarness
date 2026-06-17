"""Conditional edge routing for agents with on_pass/on_fail.

LangGraph's ``add_conditional_edges`` calls a router function that returns
the next node key (``"pass"`` / ``"fail"`` / ``"terminate"``) based on the
agent's output. The output is either a ``ReviewDecision`` model or a plain
string; both shapes are normalized here.

Three outcomes:
  - ``"pass"``: agent succeeded, route to ``on_pass`` (or END).
  - ``"fail"``: agent produced a fail decision, route to ``on_fail`` so the
    cycle can retry with the failure feedback.
  - ``"terminate"``: node was skipped due to upstream failure (or hit the
    cycle cap). Routing to ``on_fail`` would just re-skip the whole cycle
    forever, so we route to END (fail-fast the entire workflow).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from harness.constants import STATE_OUTPUTS, STATE_METADATA
from harness.engine.schema_utils import ReviewDecision
from harness.engine.state import HarnessState


def _route_decision(state: HarnessState, agent_name: str) -> str:
    """Return ``"pass"``, ``"fail"``, or ``"terminate"`` based on agent output.

    The ``"terminate"`` outcome is reserved for skipped nodes — when a node
    was bypassed because an upstream dependency failed, routing back into
    the cycle (via ``on_fail``) would loop forever since the upstream is
    still broken. Terminating the workflow is the only correct action.
    """
    outputs = state.get(STATE_OUTPUTS, {})
    output = outputs.get(agent_name)

    if output is None:
        # Distinguish "skipped because upstream failed" from "ran but
        # produced no output". The former must terminate; the latter is
        # a recoverable cycle retry.
        metadata = state.get(STATE_METADATA, {}) or {}
        node_meta = metadata.get(agent_name) if isinstance(metadata, dict) else None
        if isinstance(node_meta, dict) and node_meta.get("skipped"):
            return "terminate"
        # Also terminate when the node hit max_iterations — same rationale:
        # the cycle is exhausted, no point re-entering.
        if isinstance(node_meta, dict) and node_meta.get("max_iterations_reached"):
            return "terminate"
        return "fail"

    decision = _extract_decision(output)
    return decision if decision in ("pass", "fail") else "pass"


def _extract_decision(output: Any) -> str:
    """Extract a pass/fail decision from agent output.

    Recognized shapes:
      - ``ReviewDecision``: ``output.decision`` is canonical
      - Other ``BaseModel``: ``getattr(output, "decision")`` if present
      - ``str``: substring match (e.g. "FAIL: ..." → "fail")
      - Anything else: default to "pass"
    """
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
