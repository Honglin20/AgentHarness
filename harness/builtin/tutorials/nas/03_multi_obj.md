---
workflow: nas-multi-objective
title: 多目标优化
---

# 多目标优化

同时优化精度和延迟，找到 Pareto 最优解集。不再只看精度最高，而是在精度-延迟权衡曲线上选择最适合部署的结构。

## 定义优化目标 @objective_builder

TODO: 说明多目标优化——不只是精度，还有延迟、FLOPs、参数量
- 目标冲突：精度高往往延迟也高
- Pareto 最优：无法在不牺牲一个目标的情况下改进另一个
- 如何设置目标权重和约束（如延迟 < 10ms）
- 工具层面：**write_file** 写优化配置，**ask_user** 确认目标优先级
- 调用 [ParetoOptimizer](api/pareto_optimizer.md) 的 API

最终输出：

| 字段 | 说明 |
|------|------|
| objectives | 优化目标列表（如 accuracy, latency_ms） |
| constraints | 硬约束（如 latency_ms < 10） |
| weights | 各目标权重 |

## 执行多目标搜索 @multi_searcher

TODO: 运行多目标搜索算法
- 搜索算法：NSGA-II、MOEA/D 等进化算法
- 每一代评估种群中所有个体
- Pareto 前沿的更新和收敛判断
- 结合 [ProxyEvaluator](api/proxy_evaluator.md) 加速评估
- 搜索过程由 [ParetoOptimizer](api/pareto_optimizer.md) 驱动

最终输出：

| 字段 | 说明 |
|------|------|
| generations | 进化代数 |
| pareto_size | Pareto 前沿解的数量 |
| best_accuracy | 最高精度解 |
| best_latency | 最低延迟解 |
| convergence | 收敛状态 |

## 选择部署结构 @deploy_selector

TODO: 从 Pareto 前沿中选择适合部署目标的结构
- 根据部署场景选择（服务器优先精度，边缘优先延迟）
- 结构详情展示（每层操作、通道数）
- 导出为可部署格式
- 工具层面：**ask_user** 让用户选择偏好，**bash** 导出结构

最终输出：

| 字段 | 说明 |
|------|------|
| selected_structure | 选中的结构配置 |
| expected_accuracy | 预期精度 |
| expected_latency | 预期延迟 |
| export_path | 导出路径 |

## 生成报告 @report_painter

TODO: 多目标搜索结果可视化
- Pareto 前沿散点图（精度 vs 延迟）
- 各代 Pareto 前沿演化动画
- 选中结构的热力图
- 与单目标搜索对比
- 工具层面：**render_chart** 绘制图表

---

## 总结

TODO: 总结多目标优化的价值，强调实际部署中的权衡思维

点击左下角**「试一试」**，定义你的优化目标，找到最适合部署的网络结构。
