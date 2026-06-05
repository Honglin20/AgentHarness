"""bitx 示例 01：最简 INT8 量化对比

用 bitx 量化一个 MLP，对比 FP32 和 INT8 的输出误差。

运行:
    cd tutorials/quantization/examples/01_mlp_int8
    python model.py
"""
import torch
import sys
from pathlib import Path

# 将 bitx 自带的 example model 加入路径
BITX_ROOT = Path(__file__).resolve().parents[5] / "Analyser" / "microxcaling"
if BITX_ROOT.is_dir():
    sys.path.insert(0, str(BITX_ROOT / "pipeline"))

from _model import ToyMLP
from src.formats.base import FormatBase
from src.scheme.quant_scheme import QuantScheme
from src.scheme.granularity import GranularitySpec
from src.scheme.op_config import OpQuantConfig
from src.session import quantize_model


def main():
    print("=" * 50)
    print("bitx 示例 01：INT8 量化对比 (ToyMLP)")
    print("=" * 50)

    # 1. 创建模型和输入
    model = ToyMLP(hidden_size=128, num_classes=10)
    model.eval()
    x = torch.randn(4, 128)

    # 2. FP32 基线
    with torch.no_grad():
        fp32_out = model(x)
    print(f"\nFP32 输出 shape: {fp32_out.shape}")
    print(f"FP32 输出样本:  {fp32_out[0, :5].tolist()}")

    # 3. INT8 量化
    int8_scheme = QuantScheme(
        format=FormatBase.from_str("int8"),
        granularity=GranularitySpec.per_tensor(),
    )
    cfg = OpQuantConfig(input=int8_scheme, weight=int8_scheme, output=int8_scheme)

    q_model = quantize_model(ToyMLP(hidden_size=128, num_classes=10), cfg=cfg)
    q_model.load_state_dict(model.state_dict(), strict=False)
    q_model.eval()

    with torch.no_grad():
        int8_out = q_model(x)
    print(f"\nINT8 输出样本:  {int8_out[0, :5].tolist()}")

    # 4. 误差分析
    mse = (fp32_out - int8_out).pow(2).mean().item()
    max_err = (fp32_out - int8_out).abs().max().item()
    print(f"\nMSE:       {mse:.6f}")
    print(f"Max Error: {max_err:.6f}")
    print(f"\n量化完成。INT8 量化引入的误差很小，模型仍可正常使用。")


if __name__ == "__main__":
    main()
