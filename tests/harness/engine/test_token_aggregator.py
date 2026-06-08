"""Test token usage aggregation across agents and sub-agents."""
import pytest

from harness.engine.token_aggregator import TokenAggregator


def test_single_agent_usage():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    result = agg.get_totals()
    assert result["input"] == 100
    assert result["output"] == 50
    assert result["total"] == 150


def test_sub_agent_usage_aggregated():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.record("agent1.sub1", input_tokens=30, output_tokens=20)
    agg.record("agent1.sub2", input_tokens=40, output_tokens=10)
    result = agg.get_totals()
    assert result["input"] == 170
    assert result["output"] == 80


def test_per_agent_breakdown():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.record("agent2", input_tokens=200, output_tokens=100)
    breakdown = agg.get_breakdown()
    assert breakdown["agent1"]["total"] == 150
    assert breakdown["agent2"]["total"] == 300


def test_cache_hit_tracking():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50, cache_hit_tokens=70)
    result = agg.get_totals()
    assert result["input"] == 100
    assert result["cache_hit"] == 70


def test_reasoning_tracking():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50, reasoning_tokens=25)
    result = agg.get_totals()
    assert result["reasoning"] == 25


def test_reset():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.reset()
    assert agg.get_totals()["total"] == 0


def test_empty_totals():
    agg = TokenAggregator()
    result = agg.get_totals()
    assert result["total"] == 0
    assert result["input"] == 0


def test_multiple_record_calls_accumulate():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50)
    agg.record("agent1", input_tokens=50, output_tokens=25)
    result = agg.get_totals()
    assert result["input"] == 150
    assert result["output"] == 75


def test_breakdown_includes_cache_and_reasoning():
    agg = TokenAggregator()
    agg.record("agent1", input_tokens=100, output_tokens=50, cache_hit_tokens=30, reasoning_tokens=15)
    breakdown = agg.get_breakdown()
    assert breakdown["agent1"]["cache_hit"] == 30
    assert breakdown["agent1"]["reasoning"] == 15


def test_empty_breakdown():
    agg = TokenAggregator()
    assert agg.get_breakdown() == {}
