"""#5 — Mocked workflow showing data structures. No API key needed.

Usage:
    python examples/05_trace_demo.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
from harness.api import Agent, Workflow

class FakeUsage:
    input_tokens = 150
    output_tokens = 80
    total_tokens = 230

mock_result = MagicMock()
mock_result.output = "Task analyzed successfully."
mock_result.usage = FakeUsage()

with patch("pydantic_ai.Agent.run", new_callable=AsyncMock) as mock_run, \
     patch.object(Workflow, "setup", new_callable=AsyncMock), \
     patch.object(Workflow, "cleanup", new_callable=AsyncMock):

    mock_run.return_value = mock_result
    wf = Workflow("demo", agents=[
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
        Agent("reviewer", after=["planner"]),
    ])
    wf.compile()
    result = wf.run({"task": "demo"})

print(f"Outputs: {list(result.outputs.keys())}")

total_in = total_out = total_all = 0
print(f"\n{'Agent':<12} {'Status':<10} {'Time':>6}  {'Tokens (in/out/total)':>25}")
print("-" * 58)
for t in result.trace:
    tu = t.token_usage
    if tu:
        tokens = f"{tu.input}/{tu.output}/{tu.total}"
        total_in += tu.input; total_out += tu.output; total_all += tu.total
    else:
        tokens = "-"
    print(f"{t.agent_name:<12} {t.status:<10} {t.duration_ms:>4}ms   {tokens:>20}")
print("-" * 58)
print(f"{'TOTAL':<12} {'':10} {'':>5}     {total_in}/{total_out}/{total_all:>18}")

print(f"\nresult.model_dump():\n{result.model_dump_json(indent=2)[:200]}...")
