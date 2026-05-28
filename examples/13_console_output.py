"""#13 — ConsoleOutput：命令行美化输出。

本示例展示 ConsoleOutput Hook 的使用，用于在命令行运行时
美化输出 workflow 执行过程，包括：

1. System Prompt 显示
2. User Prompt 显示
3. 上游 Agent 输出（summary + details）
4. Agent 输出美化框
5. 执行摘要和路径追踪
6. Model / Tools / Config / Critique 信息（新增）

特点：不影响 Web UI，仅在命令行使用时激活。

用法:
    python examples/13_console_output.py
"""

from harness.api import Agent, Workflow
from harness.extensions.console import ConsoleOutput

# 创建 conditional routing workflow
wf = Workflow("console_demo", agents=[
    Agent("analyzer", after=[]),
    Agent("classifier", after=["analyzer"], on_pass="summary", on_fail="debugger"),
    Agent("summary", after=None),      # 只通过条件边触发
    Agent("debugger", after=None),    # 只通过条件边触发
])

# 使用共享 agents 目录
from pathlib import Path
wf.workflow_dir = Path(__file__).resolve().parent.parent / "workflows" / "_shared"

# 注册 ConsoleOutput（手动，不影响 UI）
# 参数说明：
#   stream=False       - 流式打印 LLM 输出
#   verbose=True       - 显示详细信息
#   show_system=True   - 显示 system prompt 框
#   show_upstream=True - 显示上游输出框
#   show_model=True    - 显示 agent 使用的 LLM model
#   show_tools=True    - 显示 agent 可用的 tools (name + description)
#   show_critique=True - 显示 eval 评审反馈（重试时）
#   show_config=True   - 显示 agent_md_path / retries / result_type
wf.use(ConsoleOutput(
    stream=False,
    verbose=True,
    show_system=True,
    show_upstream=True,
    show_model=True,
    show_tools=True,
    show_critique=True,
    show_config=True,
))

print("\n测试: analyzer → classifier → (pass→summary | fail→debugger)")
print("=" * 50)

result = wf.run({
    "task": "分析这段代码: print('hello')",
})

print(f"\n{'=' * 50}")
print("执行摘要:")
print(f"{'=' * 50}")
for t in result.trace:
    print(f"  {t.agent_name}: {t.status} ({t.duration_ms}ms)")

print(f"\n执行路径:")
for t in result.trace:
    if t.status == "success":
        print(f"  → {t.agent_name}")