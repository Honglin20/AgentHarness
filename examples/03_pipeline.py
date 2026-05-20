"""#3 — 3-agent pipeline with real LLM + full trace output.

Usage:
    python examples/03_pipeline.py
"""

from harness.api import Agent, Workflow

wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()

print("Running analyzer → planner → reviewer ...\n")
result = wf.run({"task": "Review: def div(a,b): return a/b"})

print(f"{'Agent':<12} {'Status':<10} {'Duration':>8}  {'Tokens (in/out/total)':>25}")
print("-" * 60)

total_in = total_out = total_all = 0
for t in result.trace:
    tu = t.token_usage
    if tu:
        tokens = f"{tu.input}/{tu.output}/{tu.total}"
        total_in += tu.input; total_out += tu.output; total_all += tu.total
    else:
        tokens = "-"
    print(f"{t.agent_name:<12} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

print("-" * 60)
print(f"{'TOTAL':<12} {'':10} {'':>7}     {total_in}/{total_out}/{total_all:>18}")
