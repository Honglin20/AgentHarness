---
workflow: nas-search-space
title: 搜索空间基础
badge: Quick Start
---

# 搜索空间基础

5 分钟体验一次神经网络结构搜索。你会看到框架如何定义搜索空间、训练 Supernet、采样评估候选结构，最终输出 Top-K 结果和搜索空间覆盖度分析。

## 定义搜索空间 @space_builder

TODO: 说明搜索空间是什么——把候选网络结构参数化为一个可搜索的空间
- Supernet 概念：一个大的超网络包含所有候选子结构
- 如何描述搜索空间（每层的候选操作、通道数范围、连接模式）
- 工具层面：**write_file** 写搜索空间配置，**bash** 验证配置格式
- 手动做需要翻论文找最优结构，这里自动在空间里搜索

最终输出的搜索空间配置：

| 字段 | 说明 |
|------|------|
| space_type | 搜索空间类型（如 Mobile-like, ResNet-like） |
| num_layers | 可搜索的层数 |
| op_candidates | 每层候选操作列表（如 conv3x3, conv5x5, dw_conv, skip） |
| channel_range | 通道数搜索范围 |

## 训练 Supernet @supernet_trainer

TODO: 说明 Supernet 训练——让超网络的权重共享训练，使子结构可以直接继承权重评估
- 训练配置由 [SearchSpace](api/search_space.md) 定义
- 权重共享原理：一次训练，所有子结构共享参数
- 训练策略：均匀采样、Sandwich Rule 等
- 关键超参数：learning rate、epochs、采样策略
- 工具层面：**bash** 启动训练脚本，**read_text_file** 读取训练日志
- 调用 [SearchSpace](api/search_space.md) 的配置

最终输出：

| 字段 | 说明 |
|------|------|
| supernet_path | 训练好的 Supernet 权重路径 |
| best_val_acc | 训练期间最佳验证精度 |
| train_epochs | 实际训练轮数 |
| sampling_strategy | 使用的采样策略 |

## 评估候选结构 @evaluator

TODO: 说明从 Supernet 中采样子结构并评估性能
- 评估调用 [SearchSpace](api/search_space.md) 的采样接口
- 采样策略：随机采样、进化算法、贪心选择
- 评估指标：精度、FLOPs、推理延迟、参数量
- 工具层面：**bash** 运行评估脚本
- 多指标权衡：精度最高 ≠ 最好，还要看延迟和计算量

最终输出：

| 字段 | 说明 |
|------|------|
| top_k_structures | Top-K 候选结构列表 |
| best_accuracy | 最优候选精度 |
| best_flops | 最优候选 FLOPs |
| search_coverage | 搜索空间覆盖率 |

## 生成报告 @report_painter

TODO: 说明把搜索结果可视化
- Top-K 结构精度/延迟散点图
- 搜索空间覆盖度热力图
- 各操作类型频率分布
- 工具层面：**render_chart** 绘制图表，**read_text_file** 读取评估数据

输出包含搜索结果可视化和结构分析报告。

---

## 总结

TODO: 3-5 句总结这个流程的价值，以及 Level 2 Proxy 加速搜索的预告

点击左下角**「试一试」**，输入你的模型配置，框架会自动走完整个搜索流程。
