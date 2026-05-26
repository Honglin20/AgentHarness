"""#9 — Chart 可视化：agent 通过 bash 运行脚本，脚本调用 render_chart() 推送图表到 UI。

工作原理:
  1. agent 使用 bash 工具执行 Python 脚本
  2. 脚本调用 render_chart() 生成图表数据
  3. render_chart() 通过 HTTP 发送到后端 /api/charts
  4. 后端通过 EventBus → WebSocket → 前端实时渲染

支持 8 种图表类型:
  line, bar, scatter, pareto, optimal_line, heatmap, box, table

用法（需要 UI）:
    python examples/09_charts.py                # 保存工作流
    bash examples/launch_ui.sh                  # 启动 UI
    # → 打开 http://localhost:8000
    # → 选择 "chart_demo"
    # → 任务: "Run chart_script.py"
    # → 运行 → 图表出现在中心面板
"""

from harness.api import Agent, Workflow

wf = Workflow("chart_demo", agents=[
    Agent("runner", after=[], tools=["bash"]),
])
wf.save()

print(f"已保存: workflows/{wf.name}/")
print()
print("运行步骤:")
print("  1. bash examples/launch_ui.sh")
print("  2. 打开 http://localhost:8000")
print("  3. 选择 'chart_demo'")
print("  4. 任务: Run chart_script.py")
print("  5. 运行 → 图表实时出现在面板中")
print()
print("图表类型: line, bar, scatter, pareto, optimal_line, heatmap, box, table")
