"""#10 — 持久化与 UI：保存工作流定义，通过 Web UI 运行。

AgentHarness 支持两种运行模式:
  - CLI 模式: wf.run({"task": "..."}) 直接在终端运行
  - UI 模式: 保存工作流 → 启动 Web 服务 → 浏览器中可视化运行

本示例展示完整的 save → load → run 流程，
以及如何通过 UI 启动。

用法:
    python examples/10_save_load_ui.py            # 保存 + CLI 运行
    python examples/10_save_load_ui.py --save     # 仅保存，用于 UI
"""

import sys
from harness.api import Agent, Workflow

# ── 1. 定义并保存 ──────────────────────────────────────────

wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
path = wf.save()
print(f"已保存: {path}\n")

# ── 2. 列出所有已保存的工作流 ─────────────────────────────

print("已保存的工作流:")
for w in Workflow.list_saved():
    nodes = w["dag"]["nodes"]
    print(f"  {w['name']}: {' → '.join(nodes)}")
print()

# ── 3. 仅保存模式 ─────────────────────────────────────────

if "--save" in sys.argv:
    print("启动 UI:")
    print("  bash examples/launch_ui.sh")
    print("  打开 http://localhost:8000 → 选择工作流 → 运行")
    sys.exit(0)

# ── 4. 加载并运行 ─────────────────────────────────────────

wf2 = Workflow.load("code_review")
result = wf2.run({"task": "用一句话总结 Python 的优势。"})

print(f"{'Agent':<12} {'状态':<10} {'耗时':>8}  {'Tokens':>25}")
print("-" * 60)

for t in result.trace:
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "-"
    print(f"{t.agent_name:<12} {t.status:<10} {t.duration_ms:>6}ms   {tokens:>20}")

print(f"\n各 agent 输出:")
for agent in wf2.agents:
    output = result.outputs.get(agent.name, "")
    if output:
        print(f"\n[{agent.name}]\n{output.strip()[:200]}")
