"""#8 — EvalJudge：自动插入评审节点，评估 agent 输出质量。

DAG（EvalJudge 自动改写前）:
    researcher → writer

DAG（EvalJudge 改写后）:
    researcher → _judge_researcher → writer
                    │
                  fail → researcher（注入批评意见后重试）

使用方式：
  1. 给需要评审的 agent 设置 eval=True
  2. 在 Workflow 上注册 .use(EvalJudge())

EvalJudge 是一个 GraphMutator，在编译时自动插入评审节点。
评审节点会：
  - 自动总结目标 agent 的提示词构建评审标准
  - 评估输出质量，给出 pass/fail + 分数
  - fail 时注入批评意见，重新执行目标 agent（最多重试 max_retries 次）
  - 评审分数通过 chart.render 事件推送到 UI

用法:
    python examples/08_eval_judge.py            # 保存并运行
    python examples/08_eval_judge.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = (
    Workflow("eval_demo", agents=[
        Agent("researcher", after=[], eval=True, tools=["bash"]),
        Agent("writer", after=["researcher"]),
    ])
    .use(EvalJudge(max_retries=2))
)
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  researcher → _judge_researcher → writer")
    print("                        │")
    print("                      fail")
    print("                        ↓")
    print("                    researcher（注入批评，重试）")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print(f"已保存: workflows/{wf.name}/")
print()
print("运行 researcher → _judge_researcher → writer ...\n")

result = wf.run({"task": "调研 Python 3.13 的新特性，给出简要总结。"})

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
