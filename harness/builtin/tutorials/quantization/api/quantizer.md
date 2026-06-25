# Quantizer

将 FP32 模型量化为指定比特宽度，支持均匀量化和混合精度配置。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| model | nn.Module | — | 待量化的 PyTorch 模型 |
| w_bits | int | 8 | 权重比特数（2/4/8） |
| a_bits | int | 8 | 激活比特数（2/4/8） |
| calib_loader | DataLoader | — | 校准数据集，用于统计激活范围 |
| block_size | int | 128 | 分块量化粒度，越大精度越高、速度越慢 |
| exclude_layers | list[str] | [] | 排除量化的层名（如最后的分类头） |

## 示例

```python
from bitx import Quantizer

q = Quantizer(w_bits=4, a_bits=4, block_size=128)
result = q.quantize(model, calib_loader)
print(f"FP32: {result.fp32_accuracy:.2%} → INT4: {result.quant_accuracy:.2%}")
```

## 输出

返回 `QuantizeResult`，包含：

| 字段 | 说明 |
|------|------|
| quant_accuracy | 量化后精度 |
| fp32_accuracy | FP32 基线精度 |
| accuracy_delta | 精度差值 |
| per_layer_qsnr | 每层量化信噪比（dB） |
| worst_layer | QSNR 最差的层名 |
| model_size_mb | 量化后模型大小 |
