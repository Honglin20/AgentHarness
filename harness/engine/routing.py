"""Conditional edge routing for agents with on_pass/on_fail.

LangGraph's ``add_conditional_edges`` calls a router function that returns
the next node key (``"pass"`` / ``"fail"``) based on the agent's output.
The output is either a ``ReviewDecision`` model or a plain string; both
shapes are normalized here.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from harness.constants import STATE_OUTPUTS
from harness.engine.schema_utils import ReviewDecision
from harness.engine.state import HarnessState


def _route_decision(state: HarnessState, agent_name: str) -> str:
    """Return ``"pass"`` or ``"fail"`` based on the agent's last output.

    If the node produced no output (e.g. failed before producing one),
    route to ``"fail"`` rather than silently defaulting to ``"pass"``.
    """
    outputs = state.get(STATE_OUTPUTS, {})
    output = outputs.get(agent_name)

    if output is None:
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
