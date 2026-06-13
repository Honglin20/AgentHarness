#!/usr/bin/env python
"""measure_onnx_latency.py — benchmark ONNX model latency via onnxruntime.

读取:
  - <onnx path>                 — ONNX 模型文件（由 export_onnx.py 产生）

写入:
  - <output json path>          — latency 统计

输出 (stdout JSON):
  - {latency_ms_median, latency_ms_p95, latency_ms_mean, n_runs, warmup, onnx_path}

指标 (lower is better):
  - latency_ms_median           — 中位数 (ms/sample)，主指标，抗 outliers
  - latency_ms_p95              — 95 分位
  - latency_ms_mean             — 均值

调用方: export_onnx.py 后跑此脚本，结果供 judger/fitness.py 的 --use-onnx-latency 使用。
依赖: onnxruntime, numpy。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Measure ONNX model latency")
    p.add_argument("--onnx", required=True, help="ONNX model path")
    p.add_argument("--out", required=True, help="Output JSON path")
    p.add_argument("--input-shape", default="1,64",
                   help="Comma-separated: batch,in_dim")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--n-runs", type=int, default=100)
    args = p.parse_args()

    try:
        import onnxruntime as ort
        import numpy as np
    except ImportError as e:
        print(json.dumps({"error": f"Missing dependency: {e}. pip install onnxruntime numpy"}))
        sys.exit(1)

    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name

    shape = [int(x) for x in args.input_shape.split(",")]
    dummy = np.random.randn(*shape).astype("float32")

    # Warmup (CPU thread pool spin-up, lazy init)
    for _ in range(args.warmup):
        sess.run(None, {input_name: dummy})

    batch = shape[0]
    times = []
    for _ in range(args.n_runs):
        t0 = time.perf_counter()
        sess.run(None, {input_name: dummy})
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000 / batch)  # ms per sample

    sorted_times = sorted(times)
    result = {
        "latency_ms_median": statistics.median(times),
        "latency_ms_p95": sorted_times[int(0.95 * len(sorted_times)) - 1],
        "latency_ms_mean": statistics.mean(times),
        "latency_ms_stddev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "n_runs": args.n_runs,
        "warmup": args.warmup,
        "onnx_path": args.onnx,
        "input_shape": shape,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
