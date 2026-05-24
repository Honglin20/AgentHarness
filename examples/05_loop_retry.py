"""#5 — 回环重试（DAG 级别）：coder → reviewer，不通过则回到 coder 重试。

DAG:
    coder → reviewer
              ├─ pass → END
              └─ fail → coder（注入审查意见后重试）

通过 on_fail 参数实现 DAG 级别的循环。
reviewer 输出 decision: "fail" 时，框架将审查意见注入 coder 的上下文，
然后重新执行 coder。默认最多重试 3 次。

对比 example #6（sub_agent 级别迭代）：
  - #5 是 DAG 级别循环：修改后的 coder 作为新的图节点执行，全局可见
  - #6 是工具级别迭代：reviewer 在单次执行中通过 sub_agent 反复调用 coder

用法:
    python examples/05_loop_retry.py            # 直接运行
    python examples/05_loop_retry.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("loop_retry", agents=[
    Agent("coder", after=[], tools=["bash"]),
    Agent("reviewer", after=["coder"], on_fail="coder"),
])
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  coder → reviewer ── pass ──→ END")
    print("                │")
    print("              fail")
    print("                ↓")
    print("             coder（最多重试 3 次）")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print("运行 coder → reviewer（条件回环，最多 3 次）...\n")

result = wf.run({
    "task": (
        "写一个 Python 函数 binary_search(arr, target)，在有序数组中二分查找。"
        "找到返回索引，找不到返回 -1。处理空数组。写完后用 bash 验证。"
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
    print(result.outputs.get("coder", "")[:400])
    print("\n=== Reviewer 审查 ===")
    print(result.outputs.get("reviewer", "")[:400])
