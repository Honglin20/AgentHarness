"""#11 — 组合扩展：EvalJudge + AutoCompact + Plugins 协同工作。

本示例展示如何在同一个 Workflow 上组合使用多种扩展:

  - EvalJudge（GraphMutator）: 自动评审 agent 输出 + 自动生成 judge MD
  - AutoCompact（Middleware）: 对话过长时自动压缩历史消息
  - Hook 插件（自动加载）: EvalChart 折线图 + PerfMetrics Token 消耗图

扩展分类:
  - GraphMutator: 编译时改写 DAG，需要 .use() 注册
  - Middleware:   运行时依次处理消息，需要 .use() 注册
  - Hook:         运行时并发执行，自动加载（无需 .use()）

用法:
    python examples/11_all_extensions.py            # 保存并运行
    python examples/11_all_extensions.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge
from harness.extensions.compact.auto_compact import AutoCompact

wf = (
    Workflow("full_extensions", agents=[
        Agent("researcher", after=[], eval=True, tools=["bash"]),
        Agent("writer", after=["researcher"]),
    ])
    .use(EvalJudge(max_retries=1))
    .use(AutoCompact(threshold_tokens=8000))
)
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("扩展组合:")
    print("  EvalJudge    (GraphMutator) → 自动插入评审节点 + 生成 judge MD")
    print("  AutoCompact  (Middleware)   → 长对话自动压缩")
    print("  Hook 插件    (自动加载)     → EvalChart + PerfMetrics")
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
