"""#4 — 条件路由：根据 agent 输出决定下一步走哪条分支。

DAG:
    analyzer → classifier
                  ├─ pass → summary
                  └─ fail → debugger

通过 Agent 的 on_pass / on_fail 参数定义条件边。
agent 的输出必须包含 "decision" 字段（值为 "pass" 或 "fail"），
框架据此路由到对应的目标节点。

用法:
    python examples/04_conditional_routing.py            # 直接运行
    python examples/04_conditional_routing.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("conditional_route", agents=[
    Agent("analyzer", after=[]),
    Agent("classifier", after=["analyzer"], on_pass="summary", on_fail="debugger"),
    Agent("summary", after=[]),
    Agent("debugger", after=[], tools=["bash"]),
])
wf.save()

if "--save" in sys.argv:
    print(f"已保存: workflows/{wf.name}/")
    print()
    print("DAG:  analyzer → classifier")
    print("                       ├─ pass → summary")
    print("                       └─ fail → debugger")
    print()
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    sys.exit(0)

print("运行 analyzer → classifier → (pass→summary | fail→debugger) ...\n")

result = wf.run({
    "task": "分析这段代码的质量: x = 1/0",
})

print(f"{'Agent':<16} {'状态':<10} {'耗时':>8}  {'Tokens':>25}")
print("-" * 68)

for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name:<16} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

if result.errors:
    print("\n错误:")
    for name, err in result.errors.items():
        print(f"  {name}: {err[:200]}")
