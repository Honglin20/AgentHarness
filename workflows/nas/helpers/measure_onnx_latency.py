#!/usr/bin/env python
"""measure_onnx_latency.py — benchmark ONNX model latency via onnxruntime.

输入契约探测（自动，按 onnx input_names 反推）:
  - onnx session 报告 N 个 input_names
  - 调 model.dummy_inputs() 拿原始 dummy（Tensor / tuple / list / dict）
  - 按 input_names 重映射成 onnxruntime feeds dict:
      ["input"]               → {"input": dummy.numpy()}
      ["input_0", "input_1"]  → {"input_i": dummy[i].numpy()}
      ["item", "user"]        → {"item": dummy["item"].numpy(), ...}
  - 项目无 dummy_inputs + onnx 只有 1 input → fallback 用 --input-shape

读取:
  - <onnx path>                 — ONNX 模型文件（由 export_onnx.py 产生）
  - <model-dir>/model.py        — 可选 dummy_inputs 函数

写入:
  - <output json path>          — latency 统计

输出 (stdout JSON):
  - {latency_ms_median, latency_ms_p95, latency_ms_mean, n_runs, warmup, onnx_path}
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


def _build_feeds(onnx_path: str, model_dir: Path, fallback_shape: str):
    """Return (feeds_dict, input_schema) for onnxruntime.

    feeds_dict maps onnx input_name → numpy array.
    """
    try:
        import onnxruntime as ort
        import numpy as np
    except ImportError as e:
        print(json.dumps({"error": f"Missing dependency: {e}. pip install onnxruntime numpy"}))
        sys.exit(1)

    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    input_names = [i.name for i in sess.get_inputs()]

    # Try model.dummy_inputs()
    sys.path.insert(0, str(model_dir.resolve()))
    dummy = None
    try:
        from model import dummy_inputs  # type: ignore
        dummy = dummy_inputs(batch_size=1)
    except ImportError:
        pass

    feeds: dict[str, "np.ndarray"] = {}
    schema_kind = "unknown"

    if dummy is not None:
        if isinstance(dummy, dict):
            schema_kind = "dict"
            # onnx input_names correspond to sorted keys (see export_onnx._DictInputWrapper).
            for name in input_names:
                if name not in dummy:
                    raise RuntimeError(
                        f"ONNX input {name!r} not found in dummy_inputs() dict keys {list(dummy.keys())}"
                    )
                feeds[name] = dummy[name].cpu().numpy()
        elif isinstance(dummy, (list, tuple)):
            schema_kind = "list" if isinstance(dummy, list) else "tuple"
            # onnx input_names are "input_{i}" in tuple order.
            for i, name in enumerate(input_names):
                if not name.startswith("input_"):
                    raise RuntimeError(
                        f"ONNX input {name!r} does not match expected 'input_{{i}}' pattern "
                        f"for list/tuple dummy_inputs"
                    )
                idx = int(name.split("_", 1)[1])
                feeds[name] = dummy[idx].cpu().numpy()
        else:
            schema_kind = "tensor"
            if len(input_names) != 1:
                raise RuntimeError(
                    f"dummy_inputs returned a single tensor but ONNX has {len(input_names)} inputs"
                )
            feeds[input_names[0]] = dummy.cpu().numpy()
    else:
        # Fallback: single-tensor. Only valid if onnx has exactly 1 input.
        if len(input_names) != 1:
            raise RuntimeError(
                f"ONNX model has {len(input_names)} inputs ({input_names}) but model.py has no "
                f"dummy_inputs() and fallback is single-tensor only. "
                f"Add a dummy_inputs(batch_size=1) function to model.py returning the right shape."
            )
        shape = [int(x) for x in fallback_shape.split(",")]
        feeds[input_names[0]] = np.random.randn(*shape).astype("float32")
        schema_kind = "fallback"

    return feeds, sess, {"kind": schema_kind, "input_names": input_names}


def main() -> None:
    p = argparse.ArgumentParser(description="Measure ONNX model latency")
    p.add_argument("--onnx", required=True, help="ONNX model path")
    p.add_argument("--out", required=True, help="Output JSON path")
    p.add_argument("--model-dir", default=".",
                   help="Dir containing model.py with dummy_inputs() (default: cwd)")
    p.add_argument("--input-shape", default="1,64",
                   help="(fallback only) comma-separated: batch,in_dim")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--n-runs", type=int, default=100)
    args = p.parse_args()

    feeds, sess, schema = _build_feeds(args.onnx, Path(args.model_dir), args.input_shape)
    if schema["kind"] == "fallback":
        print(
            f"[measure_onnx_latency] WARNING: model.py has no dummy_inputs(); "
            f"using single-tensor fallback with shape {args.input_shape}",
            file=sys.stderr,
        )

    # Warmup
    for _ in range(args.warmup):
        sess.run(None, feeds)

    # Determine batch from the first input's dim 0 (for per-sample normalization).
    first_input = list(feeds.values())[0]
    batch = first_input.shape[0] if first_input.ndim > 0 else 1

    times = []
    for _ in range(args.n_runs):
        t0 = time.perf_counter()
        sess.run(None, feeds)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000 / batch)

    sorted_times = sorted(times)
    result = {
        "latency_ms_median": statistics.median(times),
        "latency_ms_p95": sorted_times[int(0.95 * len(sorted_times)) - 1],
        "latency_ms_mean": statistics.mean(times),
        "latency_ms_stddev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "n_runs": args.n_runs,
        "warmup": args.warmup,
        "onnx_path": args.onnx,
        "input_schema": schema,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
