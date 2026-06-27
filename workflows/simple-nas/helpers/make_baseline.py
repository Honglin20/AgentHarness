"""Generate baseline.json with strict schema validation.

Replaces LLM free-form baseline.json authoring which was producing
inconsistent schemas (top-level accuracy, latency_ms as dict, missing
metrics/full_training_duration_sec fields).

Usage:
    python make_baseline.py \
        --eval-result <baseline_eval.json from run_strategy.py> \
        --project-analysis <project_analysis.json> \
        --profile-path <baseline_profile.json or null> \
        --out <session_dir>/baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--eval-result", required=True, help="baseline_eval.json from run_strategy.py")
    p.add_argument("--project-analysis", required=True, help="project_analysis.json")
    p.add_argument("--profile-path", default=None, help="baseline_profile.json path or None")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    eval_result = json.loads(Path(args.eval_result).read_text())
    pa = json.loads(Path(args.project_analysis).read_text())

    # Extract fields from eval_result (run_strategy.py output schema)
    metrics = eval_result.get("metrics", {})
    latency_ms = eval_result.get("latency_ms")
    onnx_latency_ms = eval_result.get("onnx_latency_ms")
    onnx_path = eval_result.get("onnx_path")
    params = eval_result.get("params")
    duration_sec = eval_result.get("duration_sec", 0.0)

    # latency_ms must be float (some LLMs wrote dict like {mean, p50, p95})
    if isinstance(latency_ms, dict):
        latency_ms = latency_ms.get("mean") or latency_ms.get("p50") or 0.0
    if isinstance(onnx_latency_ms, dict):
        onnx_latency_ms = onnx_latency_ms.get("mean") or onnx_latency_ms.get("p50")
    latency_ms = float(latency_ms) if latency_ms is not None else 0.0
    if onnx_latency_ms is not None:
        onnx_latency_ms = float(onnx_latency_ms)

    # total_epochs from project_analysis.epochs_default (fallback 10)
    total_epochs = pa.get("epochs_default")
    if total_epochs is None:
        total_epochs = 10

    one_epoch_sec = float(duration_sec)
    full_T = one_epoch_sec * total_epochs

    profile_path = args.profile_path if args.profile_path and args.profile_path != "null" else None

    # Strict BaselineFile schema
    baseline = {
        "metrics": metrics,
        "latency_ms": latency_ms,
        "onnx_latency_ms": onnx_latency_ms,
        "onnx_path": onnx_path,
        "params": params if params is not None else 0,
        "one_epoch_sec": one_epoch_sec,
        "total_epochs": total_epochs,
        "full_training_duration_sec": full_T,
        "profile_path": profile_path,
    }

    # Validate (defensive)
    required_keys = {"metrics", "latency_ms", "onnx_latency_ms", "onnx_path", "params",
                     "one_epoch_sec", "total_epochs", "full_training_duration_sec", "profile_path"}
    missing = required_keys - set(baseline.keys())
    if missing:
        print(f"ERROR: missing keys {missing}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(baseline["metrics"], dict):
        print(f"ERROR: metrics must be dict, got {type(baseline['metrics']).__name__}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(baseline["latency_ms"], (int, float)):
        print(f"ERROR: latency_ms must be float, got {type(baseline['latency_ms']).__name__}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, indent=2))
    print(f"wrote {out_path}: metrics keys={list(metrics.keys())}, latency={latency_ms:.4f}, "
          f"params={params}, T_full={full_T:.1f}s")


if __name__ == "__main__":
    main()
