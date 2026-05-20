"""Real end-to-end workflow example using DeepSeek via Pydantic AI.

Prerequisites:
    export DEEPSEEK_API_KEY="sk-..."

Usage:
    python examples/real_workflow.py

Shows the complete public API surface:
    Agent, Workflow, WorkflowResult, NodeTrace, TokenUsage
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.api import Agent, Workflow


def main():
    # ── 1. Define agents ────────────────────────────────────────────
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
        Agent("reviewer", after=["planner"]),
    ]

    # ── 2. Create workflow ──────────────────────────────────────────
    agents_dir = os.path.join(os.path.dirname(__file__), "..", "agents")
    wf = Workflow("code_review_pipeline", agents=agents, agents_dir=agents_dir)

    # ── 3. Run (synchronous, no await) ──────────────────────────────
    print("Running workflow ...\n")
    result = wf.run({"task": "Review the following Python function for bugs and suggest improvements:\n\n"
                            "def divide(a, b):\n    return a / b\n\n"
                            "def read_file(path):\n    f = open(path)\n    return f.read()"})

    # ── 4. Inspect results ──────────────────────────────────────────
    print("=" * 70)
    print(f"Workflow: {wf.name}")
    print(f"Outputs:  {list(result.outputs.keys())}")
    print(f"Errors:   {list(result.errors.keys()) if result.errors else 'none'}")
    print()
    print(f"{'Agent':<12} {'Status':<10} {'Duration':>10} {'Tokens (in/out/total)':>25}")
    print("-" * 70)

    total_in = total_out = total_all = 0
    for t in result.trace:
        tu = t.token_usage
        if tu:
            tokens = f"{tu.input}/{tu.output}/{tu.total}"
            total_in += tu.input
            total_out += tu.output
            total_all += tu.total
        else:
            tokens = "-"
        print(f"{t.agent_name:<12} {t.status:<10} {t.duration_ms:>7}ms   {tokens:>20}")

    print("-" * 70)
    print(f"{'TOTAL':<12} {'':10} {'':>8}    {total_in}/{total_out}/{total_all:>18}")
    print()

    # ── 5. Show individual agent outputs ────────────────────────────
    for name, output in result.outputs.items():
        print(f"── {name} ──")
        print(output[:500])
        print()

    # ── 6. Programmatic access ──────────────────────────────────────
    trace_dict = result.model_dump()
    trace_json = result.model_dump_json(indent=2)
    print(f"Trace records: {len(trace_dict['trace'])}")
    print(f"JSON size: {len(trace_json)} chars")


if __name__ == "__main__":
    main()
