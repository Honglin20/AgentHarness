"""#8 — EvalJudge：自动评审节点，评估 agent 输出质量 + 评分 + 重试。

本示例展示一个代码质量评审 workflow：
  coder 写代码 → EvalJudge 自动评审 → 不合格则注入批评意见重写 → reviewer 审查

DAG（EvalJudge 改写前）:
    coder(eval=True) → reviewer

DAG（EvalJudge 改写后）:
    coder → _judge_coder → reviewer
               │
             fail → coder（注入批评意见，重试最多 2 次）

EvalJudge 是一个 GraphMutator，在编译时自动插入评审节点：
  1. 自动生成 _judge_coder.md 到 agents/ 目录（仅首次，不覆盖用户编辑）
  2. 自动总结被评 agent 的 MD 提示词，注入评审上下文（lazy + SHA256 缓存）
  3. 评估输出质量，返回 pass/fail + reason + score（0.0-1.0）
  4. fail 时将 reason 注入目标 agent 上下文，重新执行
  5. score 通过 chart.render 事件推送到 UI Analysis Tab（Hook 插件自动加载）
  6. pass 时原始输出透传给下游（下游看不到 ReviewDecision）

Hook 插件（EvalChartPlugin、PerfMetricsPlugin 等）自动加载，无需 .use()。

用法:
    python examples/08_eval_judge.py            # 保存并运行
    python examples/08_eval_judge.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = (
    Workflow("eval_code_quality", agents=[
        Agent("coder", after=[], eval=True, tools=["bash"]),
        Agent("reviewer", after=["coder"]),
    ])
    .use(EvalJudge(max_retries=2))
)
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  coder → _judge_coder → reviewer")
    print("                  │")
    print("                fail")
    print("                  ↓")
    print("               coder（注入批评意见，重试最多 2 次）")
    print()
    print("扩展:")
    print("  EvalJudge       (GraphMutator) → 自动评审 + 评分 + 重试回环")
    print("  Hook 插件       (自动加载)     → EvalChart 折线图 + PerfMetrics Token 图")
    print()
    print("Judge MD 文件:")
    print("  workflows/eval_code_quality/agents/_judge_coder.md")
    print("  (可手动编辑评审标准，重新运行即生效)")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print(f"已保存: workflows/{wf.name}/")
print()
print("运行 coder → _judge_coder → reviewer（含评审回环）...\n")

result = wf.run({
    "task": (
        "写一个 Python 函数 quick_sort(arr)，实现快速排序。"
        "要求：处理空列表、已排序列表、重复元素。"
        "写完后用 bash 执行测试验证。"
    ),
})

print(f"{'Agent':<24} {'状态':<10} {'耗时':>8}  {'Tokens':>25}")
print("-" * 76)

total_in = total_out = total_all = 0
for t in result.trace:
    tu = t.token_usage
    if tu:
        tokens = f"{tu.input}/{tu.output}/{tu.total}"
        total_in += tu.input
        total_out += tu.output
        total_all += tu.total
    else:
        tokens = "-"
    print(f"{t.agent_name:<24} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

print("-" * 76)
print(f"{'合计':<24} {'':10} {'':>7}   {total_in}/{total_out}/{total_all}")

if result.errors:
    print("\n错误:")
    for name, err in result.errors.items():
        print(f"  {name}: {err[:200]}")
else:
    print("\n=== Coder 输出 ===")
    coder_output = result.outputs.get("coder", "")
    if isinstance(coder_output, str):
        print(coder_output[:500])
    else:
        print(str(coder_output)[:500])

    print("\n=== Reviewer 审查 ===")
    reviewer_output = result.outputs.get("reviewer", "")
    if isinstance(reviewer_output, str):
        print(reviewer_output[:500])
    else:
        print(str(reviewer_output)[:500])
