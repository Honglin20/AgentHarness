"""#11 — 组合扩展：EvalJudge + AutoCompact + Plugins 协同工作。

本示例展示如何在同一个 Workflow 上组合使用多种扩展:

  - EvalJudge（GraphMutator）: 自动评审 agent 输出
  - AutoCompact（Middleware）: 对话过长时自动压缩历史消息
  - EvalChartPlugin（Hook）: 将评审分数渲染为折线图

扩展执行顺序:
  1. 编译时: GraphMutator 改写 DAG
  2. 运行时: Middleware 依次处理（按注册顺序）
  3. 运行时: Hook 并发执行（不阻塞主流程）

用法:
    python examples/11_all_extensions.py            # 保存并运行
    python examples/11_all_extensions.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge
from harness.extensions.compact.auto_compact import AutoCompact
from harness.extensions.plugins.eval_chart import EvalChartPlugin

wf = (
    Workflow("full_extensions", agents=[
        Agent("researcher", after=[], eval=True, tools=["bash"]),
        Agent("writer", after=["researcher"]),
    ])
    .use(EvalJudge(max_retries=1))
    .use(AutoCompact(threshold_tokens=8000))
    .use(EvalChartPlugin())
)
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("扩展组合:")
    print("  EvalJudge    (GraphMutator) → 自动插入评审节点")
    print("  AutoCompact  (Middleware)   → 长对话自动压缩")
    print("  EvalChart    (Hook)         → 评审分数折线图")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print(f"已保存: workflows/{wf.name}/")
print()
print("运行中（EvalJudge + AutoCompact + EvalChartPlugin）...\n")

result = wf.run({"task": "调研 LangGraph 和 Pydantic AI 的核心区别。"})

print(f"{'Agent':<24} {'状态':<10} {'耗时':>8}  {'Tokens':>25}")
print("-" * 76)

for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name:<24} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

if result.errors:
    print("\n错误:")
    for name, err in result.errors.items():
        print(f"  {name}: {err[:200]}")
