"""#6 — Full loop: define agent → save workflow → run with UI.

Starts the backend server, opens a browser tab showing real-time execution:
DAG visualization, streaming output, trace, token tracking.

Usage:
    python examples/06_agent_to_ui.py
"""

from harness.api import Agent, Workflow

# 1. Define
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()

# 2. Run + open browser (auto-starts server if needed)
result = wf.run({"task": "Review: def div(a,b): return a/b"}, ui=True)

# 3. Same result as CLI mode
for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name}: {t.status} {t.duration_ms}ms tokens={tokens}")
