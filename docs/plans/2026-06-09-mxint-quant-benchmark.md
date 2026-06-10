# Plan: microxcaling 量化 baseline benchmark

**日期**: 2026-06-09
**目标**: 给 AgentHarness 的 mxint-analysis workflow 建 baseline benchmark，跑 3 个预训练模型，验证 workflow 端到端能跑通 + 给后续 scoring 优化打基础。

---

## 决策摘要（已与用户确认）

| 维度 | 决策 |
|------|------|
| 测试对象 | AgentHarness workflow（mxint-analysis）|
| 覆盖模型 | 3 个：mnist_mlp / transformer_agnews / shakespeare_gpt |
| 路径策略 | 绝对路径，写死在 task 文本里（不可移植，本机跑） |
| 评分模式 | efficiency（success / duration / tokens），初始不设 thresholds |

## 为什么 3 个 task 而不是 6 个

mxint-analysis workflow 的 CLI（`bitx.api.mxint_error_analysis`）自动跑全 quant format 对比（int8 / int4 / mxfp4 ...），不接收 quant config 参数。所以"3 模型 × 2 配置"是重复劳动，正确粒度是"3 模型 × 1 task"。

## task 文本设计原则

- **绝对路径**：让 analyzer 用 grep/glob 直接定位
- **明确提示已有 adapter**：mnist 有 `_adapter_mnist.py`，transformer / shakespeare 没有，让 workflow 自己生成（测不同难度）
- **统一目标**：跑完整 MXINT 量化误差分析 + 出报告

## 难度阶梯（验证 workflow 不同场景）

| task | 模型 | 已有 adapter | 难度 |
|------|------|--------------|------|
| mnist_mlp | MLP | ✓ `_adapter_mnist.py` | 低（直接复用） |
| transformer_agnews | Transformer encoder | ✗（需要 configurator 生成） | 中（vocab + 分词器需要处理） |
| shakespeare_gpt | decoder-only GPT | ✗（需要 configurator 生成） | 高（生成任务 + KV cache） |

## 文件落地

```
benchmarks/mxint-quant-baseline/
└── benchmark.json   # 3 个 task + efficiency scoring（初始无 thresholds）
```

## 验证步骤

1. 创建 benchmark.json
2. 重启 server，从 UI 确认 `mxint-quant-baseline` 出现在 Benchmarks 列表
3. 选第一个 task（mnist，最简单）单独跑一次，看 5 个 agent 能否串完
4. 第一个跑通后，跑全 3 个 task，看 transformer / shakespeare 能否被 configurator 自动生成 adapter
5. 拿到实际 duration / token 数据后，回头补 scoring.thresholds（让分数有区分度）

## 后续（本 plan 不包含）

- 如 transformer / shakespeare 因为权重格式复杂跑不通，可能需要在 microxcaling 项目里补两个 adapter 文件，或者让 configurator 学习样本更精细
- 跑通后可以加 LLM-as-Judge 评 report_painter 出的报告质量
- 跨 workflow 对比（同一组模型在 mxint-analysis / mxint-diagnostic / precision-diagnostic 上的输出）
