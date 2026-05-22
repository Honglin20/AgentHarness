"""#4 — Charts in the UI: agent runs a script that calls render_chart().

Design:
  - workflows/chart_demo/scripts/chart_script.py — generates data, calls render_chart()
  - render_chart() is NOT an agent tool — it's called by developer code
  - The agent just uses bash to run the script
  - render_chart() in the subprocess uses HTTP fallback (HARNESS_SERVER_URL
    set by server lifespan) → POST /api/charts → EventBus → WebSocket → UI

Usage:
    python examples/04_chart_demo.py   # save the workflow
    bash examples/launch_ui.sh         # start server + frontend
    # → Open http://localhost:8000
    # → Select "chart_demo" from dropdown
    # → Task: "Run chart_script.py"
    # → Click Run Workflow → charts appear in center panel
"""

from harness.api import Agent, Workflow

wf = Workflow("chart_demo", agents=[
    Agent("runner", after=[], tools=["bash"]),
])
wf.save()
print(f"Saved: workflows/{wf.name}/")
print()
print("To see charts in the frontend:")
print("  1. bash examples/launch_ui.sh")
print("  2. Open http://localhost:8000")
print("  3. Select 'chart_demo' from dropdown")
print("  4. Task:  Run chart_script.py")
print("  5. Click Run Workflow → charts appear in center panel")
print()
print("The agent runs the script via bash. The script calls render_chart().")
print("Charts are pushed via HTTP to the server, then WebSocket to the UI.")
