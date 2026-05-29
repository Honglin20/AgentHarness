"""Operating Envelope -- budget gates for workflow execution.

Checks accumulated token usage, tool call steps, and elapsed wall-clock time
against configured limits. Returns an error message when any budget is exceeded.
"""

from typing import Any


def check_envelope(
    accumulated_tokens: dict[str, int],
    accumulated_steps: int,
    elapsed_ms: int,
    envelope: dict[str, Any],
) -> str | None:
    """Check if accumulated totals exceed any budget limit.

    Args:
        accumulated_tokens: {"input": N, "output": N, "total": N}
        accumulated_steps: total tool call count across all nodes
        elapsed_ms: wall-clock time since workflow start
        envelope: {"max_tokens": N, "max_steps": N, "max_duration_ms": N}

    Returns:
        Error message string if budget exceeded, None if within budget.
    """
    max_tokens = envelope.get("max_tokens")
    if max_tokens and accumulated_tokens.get("total", 0) > max_tokens:
        return f"Token budget exceeded: {accumulated_tokens['total']} > {max_tokens}"

    max_steps = envelope.get("max_steps")
    if max_steps and accumulated_steps > max_steps:
        return f"Step budget exceeded: {accumulated_steps} > {max_steps}"

    max_duration = envelope.get("max_duration_ms")
    if max_duration and elapsed_ms > max_duration:
        return f"Duration budget exceeded: {elapsed_ms}ms > {max_duration}ms"

    return None
