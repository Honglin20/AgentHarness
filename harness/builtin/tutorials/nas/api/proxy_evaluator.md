# ProxyEvaluator

用零成本代理指标（无需训练）预测子结构的真实精度，将评估速度提升 10-50 倍。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| proxy_type | str | "naswot" | Proxy 类型（naswot / syncflow / zen） |
| batch_size | int | 32 | Proxy 评估时使用的 batch size |
| data_loader | DataLoader | — | 用于 Proxy 评估的数据集 |
| n_samples | int | 1 | 重复采样次数（取均值提高稳定性） |

## 示例

```python
from naslib import ProxyEvaluator, SearchSpace

space = SearchSpace(num_layers=8)
proxy = ProxyEvaluator(proxy_type="naswot", data_loader=val_loader)

# 批量评估 1000 个候选结构
scores = proxy.rank(space, top_k=50)
print(f"Top-50 accuracy proxy: {scores[0]:.4f}")
```

## 输出

返回 `ProxyResult`，包含：

| 字段 | 说明 |
|------|------|
| scores | 各候选结构的 Proxy 分数 |
| ranking | 按 Proxy 分数排序的结构索引 |
| kendall_tau | Proxy 与真实精度排序相关性 |
| eval_time_ms | 评估总耗时 |
