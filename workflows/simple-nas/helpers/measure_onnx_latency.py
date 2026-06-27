#!/usr/bin/env python
"""measure_onnx_latency.py — benchmark ONNX model latency via onnxruntime.

Pure function contract (the user-replaceable interface):
    measure_latency(onnx_path: str, ...) -> dict
    Returns: {latency_ms_median, latency_ms_p95, latency_ms_mean,
              latency_ms_stddev, n_runs, warmup, onnx_path, input_schema}

Users replace the body of ``measure_latency`` to plug in their own backend
(e.g. custom hardware, Triton, TensorRT). Setup_align writes the chosen
backend path to ``setup_contract.latency.measure_fn``; the calling agent
imports and invokes the function dynamically.

输入契约探测（自动，按 onnx input_names 反推）:
  - onnx session 报告 N 个 input_names
  - 调 model.dummy_inputs() 拿原始 dummy（Tensor / tuple / list / dict）
  - 按 input_names 重映射成 onnxruntime feeds dict
  - 项目无 dummy_inputs + onnx 只有 1 input → fallback 用 input_shape

CLI mode (backward compatible with pre-refactor callers):
    python measure_onnx_latency.py --onnx <path> --out <json path> \
        [--model-dir <dir>] [--input-shape <b,in_dim>] \
        [--warmup N] [--n-runs N]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any


def _build_feeds(onnx_path: str, model_dir: Path, fallback_shape: str):
    """Return (feeds_dict, sess, schema_info) for onnxruntime.

    feeds_dict maps onnx input_name → numpy array.
    """
    try:
        import onnxruntime as ort
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            f"Missing dependency: {e}. pip install onnxruntime numpy"
        ) from e

    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    input_names = [i.name for i in sess.get_inputs()]

    sys.path.insert(0, str(model_dir.resolve()))
    dummy = None
    try:
        from model import dummy_inputs  # type: ignore
        dummy = dummy_inputs(batch_size=1)
    except ImportError:
        pass

    feeds: dict[str, Any] = {}
    schema_kind = "unknown"

    if dummy is not None:
        if isinstance(dummy, dict):
            schema_kind = "dict"
            for name in input_names:
                if name not in dummy:
                    raise RuntimeError(
                        f"ONNX input {name!r} not found in dummy_inputs() dict keys {list(dummy.keys())}"
                    )
                feeds[name] = dummy[name].cpu().numpy()
        elif isinstance(dummy, (list, tuple)):
            schema_kind = "list" if isinstance(dummy, list) else "tuple"
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


def measure_latency(
    onnx_path: str,
    model_dir: str = ".",
    input_shape: str = "1,64",
    warmup: int = 10,
    n_runs: int = 100,
) -> dict:
    """Pure function — measure ONNX model latency. User-replaceable.

    Default impl: onnxruntime CPU, 10 warmup + 100 measured runs,
    per-sample normalized (divide by batch dim 0).

    Args:
        onnx_path: Path to .onnx file.
        model_dir: Directory containing model.py with dummy_inputs(). Default cwd.
        input_shape: Comma-separated fallback shape "batch,in_dim" when no dummy_inputs.
        warmup: Warmup runs (excluded from stats).
        n_runs: Measured runs.

    Returns:
        {latency_ms_median, latency_ms_p95, latency_ms_mean, latency_ms_stddev,
         n_runs, warmup, onnx_path, input_schema}

    Raises:
        RuntimeError: missing onnxruntime/numpy, dummy_inputs shape mismatch,
                      multi-input ONNX without dummy_inputs.
    """
    feeds, sess, schema = _build_feeds(onnx_path, Path(model_dir), input_shape)
    if schema["kind"] == "fallback":
        print(
            f"[measure_latency] WARNING: model.py has no dummy_inputs(); "
            f"using single-tensor fallback with shape {input_shape}",
            file=sys.stderr,
        )

    for _ in range(warmup):
        sess.run(None, feeds)

    first_input = list(feeds.values())[0]
    batch = first_input.shape[0] if first_input.ndim > 0 else 1

    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        sess.run(None, feeds)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000 / batch)

    sorted_times = sorted(times)
    p95_idx = max(0, int(0.95 * len(sorted_times)) - 1)
    return {
        "latency_ms_median": statistics.median(times),
        "latency_ms_p95": sorted_times[p95_idx],
        "latency_ms_mean": statistics.mean(times),
        "latency_ms_stddev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "n_runs": n_runs,
        "warmup": warmup,
        "onnx_path": onnx_path,
        "input_schema": schema,
    }


def main() -> None:
    """CLI wrapper — calls measure_latency and writes result to --out."""
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

    try:
        result = measure_latency(
            onnx_path=args.onnx,
            model_dir=args.model_dir,
            input_shape=args.input_shape,
            warmup=args.warmup,
            n_runs=args.n_runs,
        )
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
