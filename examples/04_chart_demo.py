"""#4 — Charts in the UI: save workflow, launch UI, run, watch charts appear.

How it works:
  1. This script saves a workflow with a chart_demo agent
  2. The agent has render_chart as a tool — it can create visualizations
  3. Inside the server process, render_chart() pushes via EventBus → WebSocket
  4. Charts appear in real time in the frontend center panel

Usage:
    python examples/04_chart_demo.py   # save the workflow
    bash examples/launch_ui.sh         # start server (serves API + frontend)
    # → Open http://localhost:8000
    # → Select "chart_demo" from workflow dropdown
    # → Type a task like: "Show me a line chart of score over iterations"
    # → Click Run Workflow → charts appear in the center panel
"""

from harness.api import Agent, Workflow

wf = Workflow("chart_demo", agents=[
    Agent("chart_demo", after=[], tools=["render_chart"]),
])
wf.save()
print(f"Saved: workflows/{wf.name}.json")
print()
print("To see charts in the frontend:")
print("  1. bash examples/launch_ui.sh")
print("  2. Open http://localhost:8000")
print("  3. Select 'chart_demo' from dropdown")
print("  4. Enter task, e.g.: 'Show me a line chart of score over iterations'")
print("  5. Click Run Workflow → charts appear")
