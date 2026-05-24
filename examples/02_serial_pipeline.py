"""#2 — 串行流水线：3 个 agent 依次执行。

DAG:
    analyzer → planner → reviewer

上游 agent 的输出自动传递给下游 agent 作为上下文。
每个 agent 的行为由 agents/<name>.md 定义。

用法:
    python examples/02_serial_pipeline.py
"""

from harness.api import Agent, Workflow

wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
wf.save()

print("运行 analyzer → planner → reviewer ...\n")
result = wf.run({"task": "审查这段代码: def div(a,b): return a/b"})

print(f"{'Agent':<12} {'状态':<10} {'耗时':>8}  {'Tokens (in/out/total)':>25}")
print("-" * 60)

total_in = total_out = total_all = 0
for t in result.trace:
    tu = t.token_usage
    if tu:
        tokens = f"{tu.input}/{tu.output}/{tu.total}"
        total_in += tu.input; total_out += tu.output; total_all += tu.total
    else:
        tokens = "-"
    print(f"{t.agent_name:<12} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

print("-" * 60)
print(f"{'合计':<12} {'':10} {'':>7}     {total_in}/{total_out}/{total_all}")

print(f"\n--- 各 agent 输出 ---")
for agent in wf.agents:
    output = result.outputs.get(agent.name, "")
    if output:
        print(f"\n[{agent.name}]\n{output.strip()[:300]}")
