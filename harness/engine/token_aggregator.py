"""Token usage aggregator — tracks per-agent and total token consumption."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentUsage:
    """Accumulated token usage for a single agent (or sub-agent)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenAggregator:
    """Accumulates token usage across primary agents and sub-agents.

    Usage::

        agg = TokenAggregator()
        agg.record("agent1", input_tokens=100, output_tokens=50)
        agg.record("agent1.sub1", input_tokens=30, output_tokens=20)
        totals = agg.get_totals()        # {"input": 130, "output": 70, ...}
        breakdown = agg.get_breakdown()  # per-agent dict
    """

    def __init__(self) -> None:
        self._usage: dict[str, AgentUsage] = {}

    def record(
        self,
        agent_name: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_hit_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        """Record token usage for an agent call. Values are additive."""
        if agent_name not in self._usage:
            self._usage[agent_name] = AgentUsage()
        u = self._usage[agent_name]
        u.input_tokens += input_tokens
        u.output_tokens += output_tokens
        u.cache_hit_tokens += cache_hit_tokens
        u.reasoning_tokens += reasoning_tokens

    def get_totals(self) -> dict[str, int]:
        """Return aggregated totals across all recorded agents."""
        totals = AgentUsage()
        for u in self._usage.values():
            totals.input_tokens += u.input_tokens
            totals.output_tokens += u.output_tokens
            totals.cache_hit_tokens += u.cache_hit_tokens
            totals.reasoning_tokens += u.reasoning_tokens
        return {
            "input": totals.input_tokens,
            "output": totals.output_tokens,
            "total": totals.total,
            "cache_hit": totals.cache_hit_tokens,
            "reasoning": totals.reasoning_tokens,
        }

    def get_breakdown(self) -> dict[str, dict[str, int]]:
        """Return per-agent token usage breakdown."""
        return {
            name: {
                "input": u.input_tokens,
                "output": u.output_tokens,
                "total": u.total,
                "cache_hit": u.cache_hit_tokens,
                "reasoning": u.reasoning_tokens,
            }
            for name, u in self._usage.items()
        }

    def reset(self) -> None:
        """Clear all recorded usage."""
        self._usage.clear()
