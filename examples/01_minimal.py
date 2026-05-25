"""#1 — 最小示例：定义一个 agent，运行，打印结果。

这是 AgentHarness 的最简用法。一个 Workflow 由若干 Agent 组成，
Agent 的行为由 agents/<name>.md 文件定义（提示词 + 工具配置）。

用法:
    python examples/01_minimal.py
"""

from harness.api import Agent, Workflow

wf = Workflow("hello", agents=[Agent("analyzer", after=[])])
result = wf.run({"task": "用一句话解释什么是 AI Agent。"})

print("输出:", result.outputs["analyzer"])

t = result.trace[0]
tu = t.token_usage
print(f"追踪: {t.agent_name} | {t.status} | {t.duration_ms}ms", end="")
if tu:
    print(f" | tokens {tu.input}/{tu.output}/{tu.total}")
else:
    print()
