# SearchSpace

定义神经网络结构搜索的候选空间，参数化描述每层的候选操作和通道范围。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| space_type | str | "mobile" | 搜索空间类型（mobile / resnet / custom） |
| num_layers | int | 8 | 可搜索的层数 |
| op_candidates | list[str] | ["conv3x3", "conv5x5", "dw_conv", "skip"] | 每层候选操作列表 |
| channel_range | tuple[int, int] | (16, 64) | 通道数搜索范围 |
| stem_channels | int | 32 | 初始 stem 层通道数 |
| num_classes | int | 10 | 分类数 |

## 示例

```python
from naslib import SearchSpace

space = SearchSpace(
    space_type="mobile",
    num_layers=8,
    op_candidates=["conv3x3", "dw_conv3x3", "sep_conv3x3", "skip"],
    channel_range=(16, 48),
)
print(f"Search space size: {space.size()}")  # e.g., 4^8 = 65536
```

## 输出

返回 `SearchSpaceConfig` 对象，包含：

| 字段 | 说明 |
|------|------|
| size | 搜索空间中候选结构总数 |
| layers | 每层的候选操作和通道配置 |
| supernet_class | 对应的 Supernet 类名 |
