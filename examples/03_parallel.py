"""#3 — 并行执行：两个 agent 同时运行，结果由第三个 agent 合并。

DAG:
    researcher_a ──┐
                    ├── synthesizer
    researcher_b ──┘

LangGraph 自动识别没有依赖关系的 agent 并行执行。
fan-in 节点（synthesizer）等待所有上游完成后才启动。

用法:
    python examples/03_parallel.py            # 直接运行
    python examples/03_parallel.py --save     # 仅保存，用于 UI
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
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  researcher_a ──┐")
    print("                       ├── synthesizer")
    print("      researcher_b ──┘")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print("运行 researcher_a ∥ researcher_b → synthesizer ...\n")

result = wf.run({"task": "分析当前项目的代码结构，给出综合报告。"})

print(f"{'Agent':<16} {'状态':<10} {'耗时':>8}  {'Tokens':>25}")
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
print(f"{'合计':<16} {'':10} {'':>7}     {total_in}/{total_out}/{total_all}")

if not result.errors:
    print("\n=== synthesizer 综合报告 ===")
    print(result.outputs.get("synthesizer", "")[:600])
