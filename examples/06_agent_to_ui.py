"""#6 — Define workflow → Save → Launch UI → Run from browser.

Usage:
    # Step 1: Save the workflow
    python examples/06_agent_to_ui.py

    # Step 2: Start the UI
    bash examples/launch_ui.sh

    # Step 3: Open http://localhost:3000
    #   → Select "code_review" from dropdown
    #   → Enter your task
    #   → Click "Run Workflow"
    #   → Watch DAG + streaming output + trace in real time
"""

from harness.api import Agent, Workflow

# Define & save
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()
print(f"Saved: workflows/{wf.name}.json")
print()
print("Now launch the UI:")
print("  bash examples/launch_ui.sh")
print()
print("Then open http://localhost:3000, pick 'code_review', and run.")
