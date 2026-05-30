"""#7 — 人机协作：agent 通过 ask_user 向用户提出结构化问题。

DAG:
    greeter → survey → reporter

ask_user 工具支持：
  - 单选 / 多选选项
  - 自由输入（与选项并行）
  - input_type 提示（text / number / url / textarea）
  - header 标签

当 agent 调用 ask_user 时，前端弹出 AgentQuestionCard 卡片，
用户通过卡片内联提交回答，无需使用主输入框。

注意：ask_user 必须在 UI 模式下使用（需要 WebSocket 连接）。

用法:
    python examples/07_ask_human.py --save    # 保存工作流
    bash examples/launch_ui.sh                # 启动 UI
    # → 打开 http://localhost:8000
    # → 选择 "ask_user_demo" 工作流
    # → 输入任务 → 运行 → agent 在卡片中提问 → 选择/输入 → 提交
"""

import sys
from harness.api import Agent, Workflow

wf = Workflow("ask_user_demo", agents=[
    Agent("greeter", after=[], tools=["ask_user"]),
    Agent("survey", after=["greeter"], tools=["ask_user"]),
    Agent("reporter", after=["survey"]),
])
wf.save()

print(f"已保存: workflows/{wf.name}/")
print()
print("DAG:  greeter(ask_user) → survey(ask_user) → reporter")
print()
print("运行步骤（需要 UI）:")
print("  1. bash examples/launch_ui.sh")
print("  2. 打开 http://localhost:8000")
print("  3. 选择 'ask_user_demo'")
print("  4. 任务: 你好")
print("  5. greeter 卡片弹出 → 选语言 → survey 卡片弹出 → 选功能 → reporter 汇总")

if "--save" not in sys.argv:
    print()
    print("提示: 使用 --save 仅保存，不会尝试在 CLI 中运行 ask_user。")
