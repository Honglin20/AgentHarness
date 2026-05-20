"""#2 — Save a workflow, list all saved, load and run one.

Usage:
    python examples/02_save_load.py
"""

from harness.api import Agent, Workflow

# Save
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()
print(f"Saved: workflows/{wf.name}.json")

# List
for w in Workflow.list_saved():
    print(f"  {w['name']}: {len(w['agents'])} agents — {w['dag']['nodes']}")

# Load & run
wf2 = Workflow.load("code_review")
result = wf2.run({"task": "Say hello in one word."})
print(f"Loaded & ran: {list(result.outputs.keys())}")
