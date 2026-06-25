---
order: 5
color: amber
icon: Flame
status: active
workflows:
  - name: ask_user_demo
    description: ask_user 结构化问答演示（单选 / 多选 / 自由输入）
  - name: demo_chart
    description: render_chart 多图表可视化（柱状 / 折线 / 散点 / 热力图）
  - name: chart_demo
    description: 用 bash 生成数据并驱动图表渲染
  - name: code_review
    description: 三段式代码审查流水线（分析 → 规划 → 评审）
  - name: eval_code_quality
    description: 带 eval 标记的代码生成 + 自动评测反馈循环
  - name: conditional_route
    description: 条件路由（on_pass / on_fail 分叉到 summary 或 debugger）
  - name: sub_agent_test
    description: sub_agent 委派演示（一个 delegator 调度子任务）
  - name: parallel_iter_demo
    description: 并行 fan-out/fan-in + 多轮迭代收敛（NAS 风格最小 demo）
---

# Demo 演示

独立的最小可运行工作流，演示 harness 各项能力的端到端流程。每个 demo 都能从门户直接启动，方便快速复现交互、调试、观测行为。涵盖 `ask_user` 交互、图表渲染、代码审查、条件路由、sub_agent 委派、以及一个 NAS 风格的并行迭代 demo。
