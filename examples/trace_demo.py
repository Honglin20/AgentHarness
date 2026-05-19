"""Trace Demo — end-to-end example with mocked LLM.

Shows the full data flow: workflow → agents → node events → token_usage → trace.

Usage:
    cd backend && python ../examples/trace_demo.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from harness.api import Agent, Workflow, WorkflowResult


def run_demo() -> WorkflowResult:
    """Run a 3-agent workflow with mocked LLM, inspect the full trace."""
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
        Agent("reviewer", after=["planner"]),
    ]

    wf = Workflow("trace_demo", agents=agents, agents_dir="agents")

    # Mock Pydantic AI agent.run() to return fake results with token usage
    class FakeUsage:
        request_tokens = 150
        response_tokens = 80
        total_tokens = 230

    mock_result = MagicMock()
    mock_result.output = "Task analyzed successfully."
    mock_result.usage.return_value = FakeUsage()

    with patch("pydantic_ai.Agent.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result

        result = wf.run({"task": "Analyze the codebase and create a plan"})

    # ── Print Trace ──
    print("=" * 60)
    print("Workflow:", wf.name)
    print("Outputs: ", result.outputs)
    print()
    print(f"{'Agent':<12} {'Status':<10} {'Time':>8} {'Tokens (in/out/total)':>25}")
    print("-" * 55)
    total_input = total_output = total_all = 0
    for t in result.trace:
        duration = f"{t.duration_ms}ms"
        tu = t.token_usage
        if tu:
            tokens = f"{tu.input}/{tu.output}/{tu.total}"
            total_input += tu.input
            total_output += tu.output
            total_all += tu.total
        else:
            tokens = "-"
        print(f"{t.agent_name:<12} {t.status:<10} {duration:>8}   {tokens:>20}")
    print("-" * 55)
    print(f"{'TOTAL':<12} {'':10} {'':>8}   {total_input}/{total_output}/{total_all:>20}")

    if result.errors:
        print(f"\nErrors: {result.errors}")

    print("=" * 60)
    print("WorkflowResult.model_dump():")
    import json
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))

    return result


if __name__ == "__main__":
    run_demo()
