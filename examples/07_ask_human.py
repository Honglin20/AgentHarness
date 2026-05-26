"""#7 — 人机协作：agent 在执行过程中向用户提问。

DAG:
    analyzer → decision_maker（通过 ask_human 工具等待用户回答）

ask_human 工具通过 WebSocket 与前端 Chat 面板交互。
当 agent 调用 ask_human 时，工作流暂停，等待用户在前端输入回答。
收到回答后 agent 继续执行。

注意：ask_human 必须在 UI 模式下使用（需要 WebSocket 连接）。
CLI 模式下 agent 会等待直到超时。

用法:
    python examples/07_ask_human.py --save     # 保存工作流
    bash examples/launch_ui.sh                 # 启动 UI
    # → 打开 http://localhost:8000
    # → 选择 "ask_human_demo" 工作流
    # → 输入任务 → 运行 → agent 提问时在右侧 Chat 面板回答
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("ask_human_demo", agents=[
    Agent("analyzer", after=[], tools=["bash"]),
    Agent("decision_maker", after=["analyzer"], tools=["ask_human"]),
])
wf.save()

print(f"已保存: workflows/{wf.name}/")
print()
print("DAG:  analyzer → decision_maker（ask_human 等待用户回答）")
print()
print("运行步骤（需要 UI）:")
print("  1. bash examples/launch_ui.sh")
print("  2. 打开 http://localhost:8000")
print("  3. 选择 'ask_human_demo'")
print("  4. 任务: 分析这个项目应该用什么技术方案，让我做选择")
print("  5. 运行 → agent 在 Chat 面板提问 → 输入回答 → agent 继续")

if "--save" not in sys.argv:
    print()
    print("提示: 使用 --save 仅保存，不会尝试在 CLI 中运行 ask_human。")
