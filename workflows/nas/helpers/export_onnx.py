#!/usr/bin/env python
"""export_onnx.py — load PyTorch checkpoint, export to ONNX.

读取:
  - <checkpoint path>           — PyTorch .pt 文件，含 {config, model_state, train_losses}
  - cwd/model.py                — ConfigurableMLP 定义（caller 需 cd 到项目目录）

写入:
  - <output onnx path>          — ONNX 模型文件

输出 (stdout JSON):
  - {onnx_path, params, opset_version}

调用方: trainer / refiner sub_agent 训完 checkpoint 后跑此脚本。
依赖: torch (自带 torch.onnx.export)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


def main() -> None:
    p = argparse.ArgumentParser(description="Export PyTorch checkpoint to ONNX")
    p.add_argument("--checkpoint", required=True, help="PyTorch .pt checkpoint path")
    p.add_argument("--out", required=True, help="Output .onnx path")
    p.add_argument("--in-dim", type=int, default=64, help="Input feature dim")
    p.add_argument("--num-classes", type=int, default=10)
    p.add_argument("--input-shape", default="1,64",
                   help="Comma-separated dummy input shape: batch,in_dim")
    p.add_argument("--opset", type=int, default=17)
    p.add_argument("--model-dir", default=".",
                   help="Dir containing model.py (default: cwd). Set explicitly "
                        "when running from a worktree that lacks the project source.")
    args = p.parse_args()

    # Import model from --model-dir (defaults to cwd)
    sys.path.insert(0, str(Path(args.model_dir).resolve()))
    try:
        from model import ConfigurableMLP, count_parameters
    except ImportError as e:
        print(json.dumps({"error": f"Cannot import model.py from cwd: {e}"}))
        sys.exit(1)

    ckpt = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    config = ckpt["config"]

    model = ConfigurableMLP(
        in_dim=args.in_dim,
        num_classes=args.num_classes,
        hidden_dim=config["hidden_dim"],
        num_layers=config["num_layers"],
        activation=config["activation"],
        use_batchnorm=config.get("use_batchnorm", False),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    shape = [int(x) for x in args.input_shape.split(",")]
    dummy_input = torch.randn(*shape)

    torch.onnx.export(
        model, dummy_input, str(out_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=args.opset,
    )

    result = {
        "onnx_path": str(out_path),
        "params": count_parameters(model),
        "opset_version": args.opset,
    }
    out_path.with_suffix(".export_meta.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
