"""#8 — Coder 写代码 → Reviewer 审查，不通过则用 sub_agent 让 coder 修改，迭代直到通过。

DAG:
    coder → reviewer_agent (iterate via sub_agent until pass)

Usage:
    python examples/08_coder_review_loop.py           # 直接运行
    python examples/08_coder_review_loop.py --save     # 仅保存，用于 UI
    bash examples/launch_ui.sh                         # 启动 UI
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("coder_review_loop", agents=[
    Agent("coder", after=[], tools=["bash"]),
    Agent("reviewer_agent", after=["coder"], tools=["sub_agent"]),
])
wf.save()

if "--save" in sys.argv:
    print(f"Saved: workflows/{wf.name}.json")
    print("DAG: coder → reviewer_agent (iterate via sub_agent until pass)")
    print()
    print("Now launch the UI and select 'coder_review_loop':")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print(f"Saved: workflows/{wf.name}.json")
print()
print("Running coder → reviewer_agent (with sub_agent iteration) ...\n")

result = wf.run({
    "task": "写一个 Python 函数 fibonacci(n)，返回第 n 个斐波那契数。要求：处理 n<=0 返回 0，n=1 返回 1，使用迭代而非递归。"
})

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
    print("=== Coder 输出 ===")
    print(result.outputs.get("coder", "")[:300])
    print("...")
    print()
    print("=== Reviewer 审查结论 ===")
    print(result.outputs.get("reviewer_agent", "")[:400])
