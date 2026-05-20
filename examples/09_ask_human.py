"""#9 — Human-in-the-loop: agent asks user for input via ask_human tool.

DAG:
    analyzer → decision_maker (asks user via ask_human → waits → continues)

Usage (MUST use UI — ask_human requires frontend chat panel):
    python examples/09_ask_human.py --save
    bash examples/launch_ui.sh
    # → Open http://localhost:8000
    # → Select "ask_human_demo" from dropdown
    # → Task: "分析这个项目应该用什么数据库，让我做选择"
    # → Click Run Workflow
    # → When agent asks a question, answer in the right-side Chat panel
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("ask_human_demo", agents=[
    Agent("analyzer", after=[], tools=["bash"]),
    Agent("decision_maker", after=["analyzer"], tools=["ask_human"]),
])
wf.save()
print(f"Saved: workflows/{wf.name}.json")
print()
print("DAG: analyzer → decision_maker (ask_human → wait → decide)")
print()
print("To run (ask_human requires UI):")
print("  1. bash examples/launch_ui.sh")
print("  2. Open http://localhost:8000")
print("  3. Select 'ask_human_demo' from dropdown")
print("  4. Task: 分析这个项目应该用什么技术方案，让我做选择")
print("  5. Click Run Workflow")
print("  6. When agent asks a question in the Chat panel (right side), type your answer and click Send")
print("  7. Agent continues based on your answer, final result appears in center panel")
print()

if "--save" not in sys.argv:
    print("Tip: use --save to skip this message and only save the workflow.")
    print("Running ask_human workflow without UI won't work — the agent will wait 5 minutes then timeout.")
