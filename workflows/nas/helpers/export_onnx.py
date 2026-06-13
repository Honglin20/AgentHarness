#!/usr/bin/env python
"""export_onnx.py — load PyTorch checkpoint, export to ONNX.

输入契约探测（自动）:
  1. 优先 from model import dummy_inputs；存在则 dummy = dummy_inputs(batch_size=1)
     - 返回 Tensor       → 单输入
     - 返回 tuple        → 多输入 (forward(*dummy))
     - 返回 list         → 用 ListInputWrapper 把 list 输入展开成 positional args
                           (ONNX 没有 list-of-tensors 概念)
     - 返回 dict         → 用 DictInputWrapper 把 dict 输入展开成 positional args
                           (forward(*args) → forward({k: v for ...}))
  2. 不存在 → fallback 到 --input-shape 单 tensor，stderr 警告

模型类自动发现:
  1. 优先 model.MODEL_CLASS（模块级显式声明）
  2. 单个 nn.Module 子类 → 直接用
  3. 命名启发式（含 MLP/Model/Net/Network/Transformer/CNN/RNN/...）
  4. 最后定义的 nn.Module 子类

读取:
  - <checkpoint path>           — PyTorch .pt 文件，含 {config, model_state, train_losses}
  - <model-dir>/model.py        — 模型定义 + 可选 dummy_inputs / MODEL_CLASS

写入:
  - <output onnx path>          — ONNX 模型文件
  - <output>.export_meta.json   — {onnx_path, params, opset_version, input_schema}

输出 (stdout JSON):
  - {onnx_path, params, opset_version, input_schema}
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from pathlib import Path

import torch
import torch.nn as nn


class _ListInputWrapper(nn.Module):
    """Wrap a list-input model so torch.onnx.export sees positional tensor args.

    ONNX has no concept of a Python list of tensors — the list must be unfolded
    into N positional inputs at export time. measure_onnx_latency.py reads back
    the same order from the ONNX session's input_names (input_0, input_1, ...).
    """

    def __init__(self, model: nn.Module):
        super().__init__()
        self.model = model

    def forward(self, *args):
        return self.model(list(args))


class _DictInputWrapper(nn.Module):
    """Wrap a dict-input model so torch.onnx.export sees positional tensor args.

    Sorted-key order is canonical — measure_onnx_latency.py reads back the same
    order from the ONNX session's input_names.
    """

    def __init__(self, model: nn.Module, keys: list[str]):
        super().__init__()
        self.model = model
        self.keys = keys

    def forward(self, *args):
        d = {k: v for k, v in zip(self.keys, args)}
        return self.model(d)


def _find_model_class(model_module):
    """Find the user-defined nn.Module subclass in model.py.

    Resolution order:
      1. Explicit `MODEL_CLASS = X` at module level (highest priority).
      2. Single nn.Module subclass — return it.
      3. Heuristic: pick the class whose name matches MLP/Model/Net/Network/Transformer/CNN/RNN/LSTM.
      4. Last-defined nn.Module subclass (in source order via __dict__).
      5. Raise if zero candidates.
    """
    all_classes = [
        (name, obj)
        for name, obj in vars(model_module).items()
        if (
            inspect.isclass(obj)
            and issubclass(obj, nn.Module)
            and obj is not nn.Module
            and obj.__module__ == model_module.__name__
        )
    ]
    if not all_classes:
        raise RuntimeError(
            f"No nn.Module subclass defined in model.py "
            f"(looked in module {model_module.__name__})"
        )

    # 1. Explicit MODEL_CLASS
    explicit = getattr(model_module, "MODEL_CLASS", None)
    if explicit is not None:
        for _, obj in all_classes:
            if obj is explicit:
                return obj
        raise RuntimeError(
            f"MODEL_CLASS is set to {explicit!r} but is not an nn.Module subclass defined in model.py"
        )

    # 2. Single candidate
    if len(all_classes) == 1:
        return all_classes[0][1]

    # 3. Naming heuristic
    pattern = re.compile(
        r"(MLP|Model|Net|Network|Transformer|CNN|RNN|LSTM|GRU|Encoder|Decoder)",
        re.IGNORECASE,
    )
    heuristic_matches = [(n, o) for n, o in all_classes if pattern.search(n)]
    if len(heuristic_matches) == 1:
        return heuristic_matches[0][1]

    # 4. Last-defined (vars() preserves insertion order in Py3.7+)
    return all_classes[-1][1]


def _instantiate_model(model_cls, config: dict):
    """Best-effort instantiation: only pass constructor kwargs that exist in config."""
    sig = inspect.signature(model_cls.__init__)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if name in config:
            kwargs[name] = config[name]
        # Required params missing from config fall back to the constructor's default
        # (or raise); we don't try to guess them.
    return model_cls(**kwargs)


def _load_dummy_inputs(model_dir: Path, batch_size: int, fallback_shape: str):
    """Returns (dummy, schema).

    schema is a dict describing what was returned so callers / measure_onnx can adapt:
      {"kind": "tensor" | "tuple" | "list" | "dict",
       "keys": [...],            # for dict, sorted keys; for tuple/list, generated names
       "shapes": [[...], ...],   # per-input shapes
       "source": "dummy_inputs" | "fallback"}
    """
    sys.path.insert(0, str(model_dir.resolve()))
    try:
        from model import dummy_inputs  # type: ignore
    except ImportError:
        shape = [int(x) for x in fallback_shape.split(",")]
        dummy = torch.randn(*shape)
        return dummy, {
            "kind": "tensor",
            "keys": ["input"],
            "shapes": [list(dummy.shape)],
            "source": "fallback",
        }

    raw = dummy_inputs(batch_size=batch_size)

    if isinstance(raw, dict):
        keys = sorted(raw.keys())
        ordered = [raw[k] for k in keys]
        return raw, {
            "kind": "dict",
            "keys": keys,
            "shapes": [list(t.shape) for t in ordered],
            "source": "dummy_inputs",
        }
    if isinstance(raw, (list, tuple)):
        ordered = list(raw)
        keys = [f"input_{i}" for i in range(len(ordered))]
        return raw, {
            "kind": "list" if isinstance(raw, list) else "tuple",
            "keys": keys,
            "shapes": [list(t.shape) for t in ordered],
            "source": "dummy_inputs",
        }
    # Single tensor
    return raw, {
        "kind": "tensor",
        "keys": ["input"],
        "shapes": [list(raw.shape)],
        "source": "dummy_inputs",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Export PyTorch checkpoint to ONNX")
    p.add_argument("--checkpoint", required=True, help="PyTorch .pt checkpoint path")
    p.add_argument("--out", required=True, help="Output .onnx path")
    p.add_argument("--input-shape", default="1,64",
                   help="(fallback only) comma-separated dummy input shape: batch,in_dim")
    p.add_argument("--batch-size", type=int, default=1,
                   help="batch size passed to dummy_inputs() (also used for dynamic_axes dim 0)")
    p.add_argument("--opset", type=int, default=17)
    p.add_argument("--model-dir", default=".",
                   help="Dir containing model.py (default: cwd). Set explicitly "
                        "when running from a worktree that lacks the project source.")
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    sys.path.insert(0, str(model_dir.resolve()))
    import model as model_module  # noqa: E402
    try:
        from model import count_parameters  # type: ignore
    except ImportError:
        def count_parameters(m: nn.Module) -> int:
            return sum(p.numel() for p in m.parameters())

    try:
        model_cls = _find_model_class(model_module)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    ckpt = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    config = ckpt["config"]

    try:
        model = _instantiate_model(model_cls, config)
    except TypeError as e:
        print(json.dumps({
            "error": f"Cannot instantiate {model_cls.__name__} from checkpoint config: {e}",
            "config": config,
        }))
        sys.exit(1)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_dummy, schema = _load_dummy_inputs(model_dir, args.batch_size, args.input_shape)
    if schema["source"] == "fallback":
        print(
            f"[export_onnx] WARNING: model.py has no dummy_inputs(); "
            f"using single-tensor fallback with shape {schema['shapes'][0]}. "
            f"This will fail on multi-input / list / dict forward signatures.",
            file=sys.stderr,
        )

    # Determine the actual export target (model or wrapper) + positional dummy args.
    export_target = model
    if isinstance(raw_dummy, dict):
        keys = sorted(raw_dummy.keys())
        export_target = _DictInputWrapper(model, keys)
        dummy_args = tuple(raw_dummy[k] for k in keys)
    elif isinstance(raw_dummy, list):
        # ONNX has no list-of-tensors input — unfold into positional args via wrapper.
        export_target = _ListInputWrapper(model)
        dummy_args = tuple(raw_dummy)
    elif isinstance(raw_dummy, tuple):
        # multi-input forward(x1, x2, ...) — direct positional, no wrapper needed.
        dummy_args = tuple(raw_dummy)
    else:
        dummy_args = raw_dummy

    input_names = schema["keys"]
    dynamic_axes = {name: {0: "batch"} for name in input_names}
    dynamic_axes["logits"] = {0: "batch"}

    torch.onnx.export(
        export_target, dummy_args, str(out_path),
        input_names=input_names, output_names=["logits"],
        dynamic_axes=dynamic_axes,
        opset_version=args.opset,
    )

    result = {
        "onnx_path": str(out_path),
        "params": count_parameters(model),
        "opset_version": args.opset,
        "input_schema": schema,
        "model_class": model_cls.__name__,
    }
    out_path.with_suffix(".export_meta.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
