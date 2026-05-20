"""#7 — 两个 agent 并行执行，synthesizer 综合两者的结果。

DAG:
    researcher_a ──┐
                    ├── synthesizer
    researcher_b ──┘

Usage:
    python examples/07_parallel.py           # 直接运行
    python examples/07_parallel.py --save     # 仅保存，用于 UI
    bash examples/launch_ui.sh                # 启动 UI
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("parallel_research", agents=[
    Agent("researcher_a", after=[]),
    Agent("researcher_b", after=[]),
    Agent("synthesizer", after=["researcher_a", "researcher_b"]),
])
wf.save()

if "--save" in sys.argv:
    print(f"Saved: workflows/{wf.name}.json")
    print("DAG: researcher_a ──┐")
    print("                  ├── synthesizer")
    print("     researcher_b ──┘")
    print()
    print("Now launch the UI and select 'parallel_research':")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print(f"Saved: workflows/{wf.name}.json")
print()
print("Running researcher_a ∥ researcher_b → synthesizer ...\n")

result = wf.run({"task": "分析当前项目的代码结构和依赖关系，给出综合报告。"})

print(f"{'Agent':<16} {'Status':<10} {'Duration':>8}  {'Tokens (in/out/total)':>25}")
print("-" * 68)

total_in = total_out = total_all = 0
for t in result.trace:
    tu = t.token_usage
    if tu:
        tokens = f"{tu.input}/{tu.output}/{tu.total}"
        total_in += tu.input; total_out += tu.output; total_all += tu.total
    else:
        tokens = "-"
    print(f"{t.agent_name:<16} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

print("-" * 68)
print(f"{'TOTAL':<16} {'':10} {'':>7}     {total_in}/{total_out}/{total_all:>18}")
print()

if result.errors:
    print("Errors:")
    for name, err in result.errors.items():
        print(f"  {name}: {err[:200]}")
else:
    print("=== synthesizer 综合报告 ===")
    print(result.outputs.get("synthesizer", "")[:600])
    print("...")
