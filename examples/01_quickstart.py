"""#1 — Define an agent, run it, print the result.

Usage:
    python examples/01_quickstart.py
"""

from harness.api import Agent, Workflow

wf = Workflow("hello", agents=[Agent("analyzer", after=[])])
result = wf.run({"task": "Say hello in exactly 3 words."})

print("Output:", result.outputs["analyzer"])

t = result.trace[0]
tu = t.token_usage
print(f"Trace:  {t.agent_name} | {t.status} | {t.duration_ms}ms", end="")
if tu:
    print(f" | tokens {tu.input}/{tu.output}/{tu.total}")
else:
    print()
