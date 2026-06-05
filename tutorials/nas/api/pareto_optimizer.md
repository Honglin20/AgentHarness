# ParetoOptimizer

多目标进化算法优化器，同时优化精度和延迟，找到 Pareto 最优解集。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| objectives | list[str] | ["accuracy", "latency_ms"] | 优化目标列表 |
| constraints | dict | {} | 硬约束（如 {"latency_ms": 10} 表示延迟 < 10ms） |
| population_size | int | 50 | 种群大小 |
| generations | int | 30 | 进化代数 |
| crossover_prob | float | 0.9 | 交叉概率 |
| mutation_prob | float | 0.1 | 变异概率 |
| proxy | ProxyEvaluator | None | 可选 Proxy 加速评估 |

## 示例

```python
from naslib import ParetoOptimizer, SearchSpace

space = SearchSpace(num_layers=8)
optimizer = ParetoOptimizer(
    objectives=["accuracy", "latency_ms"],
    constraints={"latency_ms": 15},
    generations=30,
)

pareto = optimizer.optimize(space)
print(f"Pareto front size: {len(pareto)} solutions")
for sol in pareto[:3]:
    print(f"  acc={sol.accuracy:.2%}, latency={sol.latency_ms:.1f}ms")
```

## 输出

返回 `ParetoFront`，包含：

| 字段 | 说明 |
|------|------|
| solutions | Pareto 前沿解列表（每个含 accuracy, latency_ms, structure） |
| hypervolume | 超体积指标（衡量 Pareto 前沿质量） |
| convergence_history | 各代超体积变化（判断收敛） |
| total_evals | 总评估次数 |
