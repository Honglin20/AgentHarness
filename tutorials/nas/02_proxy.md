---
workflow: nas-proxy-search
title: Proxy 加速搜索
---

# Proxy 加速搜索

用代理模型（Proxy）替代真实训练来加速结构评估，搜索速度提升 10-50 倍。适合在大型搜索空间中快速筛选候选结构。

## 分析搜索空间 @space_analyzer

TODO: 分析现有搜索空间的规模和复杂度
- 统计搜索空间大小（候选结构总数）
- 识别瓶颈操作（计算量最大的候选）
- 判断是否需要 Proxy 加速
- 工具层面：**bash** 运行空间分析脚本，**read_text_file** 读取结果

最终输出：

| 字段 | 说明 |
|------|------|
| space_size | 搜索空间中候选结构总数 |
| bottleneck_ops | 计算瓶颈操作列表 |
| needs_proxy | 是否建议使用 Proxy 加速 |

## 构建 Proxy 评估器 @proxy_builder

TODO: 说明如何构建 Proxy——用轻量级指标预测真实精度
- Proxy 类型：零成本代理（NASWOT、SyncFlow）、部分训练、学习型代理
- 如何选择合适的 Proxy（权衡速度和相关性）
- 工具层面：**write_file** 写 Proxy 配置，**bash** 验证
- 调用 [ProxyEvaluator](api/proxy_evaluator.md) 的 API

最终输出：

| 字段 | 说明 |
|------|------|
| proxy_type | 选用的 Proxy 类型 |
| correlation | Proxy 预测与真实精度的相关系数 |
| speedup_factor | 相比真实训练的加速倍数 |

## 执行 Proxy 搜索 @proxy_searcher

TODO: 用 Proxy 替代真实训练，快速遍历搜索空间
- 用 Proxy 评估所有或大量候选结构
- 筛选 Top-K 送入真实评估验证
- Proxy 预测 vs 真实精度的对比验证
- 工具层面：**bash** 运行搜索脚本

最终输出：

| 字段 | 说明 |
|------|------|
| candidates_evaluated | Proxy 评估的候选总数 |
| top_k_verified | 真实验证的 Top-K 数量 |
| proxy_accuracy | Proxy 预测精度 |
| real_accuracy | 真实训练精度 |
| kendall_tau | Proxy-真实精度排序相关性 |

## 生成报告 @report_painter

TODO: Proxy 搜索结果可视化
- Proxy 预测 vs 真实精度散点图
- 搜索效率对比（有/无 Proxy）
- Top-K 候选结构详情
- 工具层面：**render_chart** 绘制图表

---

## 总结

TODO: 总结 Proxy 加速的价值，预告 Level 3 多目标优化

点击左下角**「试一试」**，体验 Proxy 加速的搜索流程。
