"""#10 — EvalJudge demo: auto-insert a judge node that evaluates agent output.

DAG (after EvalJudge mutates):
    researcher → _judge_researcher → writer
                  ↓ on_fail
              researcher (retry with critique)

The _judge_researcher node:
  - Lazy-summarizes researcher.md → builds evaluator prompt
  - Reviews researcher's output → returns pass/fail + score
  - On fail: loops back to researcher with ## Previous judgment critique
  - On pass: passes output through to writer (display name rewritten)
  - Emits score chart via chart.render event

Usage (MUST use UI — judge events render in real-time):
    python examples/10_eval_judge.py
    bash examples/launch_ui.sh
    # → Open http://localhost:8000
    # → Select "eval_demo" from dropdown
    # → Task: "调研 Python 3.13 的新特性"
    # → Click Run Workflow
    # → Watch: judge node evaluates researcher, score chart appears
"""

from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = (
    Workflow("eval_demo", agents=[
        Agent("researcher", after=[], eval=True, tools=["bash", "web_search"]),
        Agent("writer", after=["researcher"]),
    ])
    .use(EvalJudge(max_retries=2))
)
wf.save()
print(f"Saved: workflows/{wf.name}/")
print()
print("DAG: researcher → _judge_researcher → writer")
print("                    ↓ on_fail")
print("                researcher (retry with critique)")
print()
print("To run:")
print("  1. bash examples/launch_ui.sh")
print("  2. Open http://localhost:8000")
print("  3. Select 'eval_demo' from dropdown")
print("  4. Task:  调研 Python 3.13 的新特性")
print("  5. Click Run Workflow → watch judge evaluate + score chart")
