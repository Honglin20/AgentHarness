"""#6 — sub_agent 迭代（工具级别）：coder → reviewer，不通过则通过 sub_agent 重修。

DAG:
    coder → reviewer_agent（内部通过 sub_agent 工具迭代）

与 #5 的区别：这里 reviewer_agent 在单次执行中使用 sub_agent 工具
委托子 agent 修复代码，直到通过。迭代发生在工具调用内部，
对 DAG 来说只有 coder 和 reviewer_agent 两个节点。

适用场景：
  - #5（DAG 回环）：需要全局可见的迭代，其他 agent 也能看到每次修改
  - #6（sub_agent 迭代）：迭代是某个 agent 的内部行为，更简洁

用法:
    python examples/06_sub_agent_loop.py            # 直接运行
    python examples/06_sub_agent_loop.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("coder_review_loop", agents=[
    Agent("coder", after=[], tools=["bash"]),
    Agent("reviewer_agent", after=["coder"], tools=["sub_agent"]),
])
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  coder → reviewer_agent（sub_agent 内部迭代）")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print("运行 coder → reviewer_agent（sub_agent 迭代）...\n")

result = wf.run({
    "task": (
        "写一个 Python 函数 fibonacci(n)，返回第 n 个斐波那契数。"
        "处理 n<=0 返回 0，n=1 返回 1，使用迭代而非递归。"
    ),
})

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
    print("\n=== Coder 输出 ===")
    print(result.outputs.get("coder", "")[:300])
    print("\n=== Reviewer 审查结论 ===")
    print(result.outputs.get("reviewer_agent", "")[:400])
