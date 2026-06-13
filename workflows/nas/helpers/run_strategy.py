#!/usr/bin/env python
"""run_strategy.py — Run a NAS strategy end-to-end.

Wraps: cd worktree → git apply diff → adapter train → adapter evaluate → export_onnx → measure_latency.

Used by trainer/refiner sub_agents to eliminate task template duplication.
Writes eval_result.json to --out path.

Exit code: 0 if status="ok", 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worktree", required=True)
    p.add_argument("--diff", required=True,
                   help="path to .patch, or 'baseline' to skip git apply")
    p.add_argument("--runner", required=True,
                   help="adapter path (.nas_runner.py)")
    p.add_argument("--tier", default="{}",
                   help="JSON: {epochs, data_ratio}; null/absent dims are skipped")
    p.add_argument("--out", required=True,
                   help="eval_result.json output path")
    p.add_argument("--helpers-dir", required=True)
    p.add_argument("--strategy-id", default=None)
    p.add_argument("--gpu-id", default=None)
    args = p.parse_args()

    tier = json.loads(args.tier)
    worktree = Path(args.worktree).resolve()
    runner = Path(args.runner).resolve()
    helpers = Path(args.helpers_dir).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if args.gpu_id is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(args.gpu_id)

    result = {
        "status": "failed",
        "strategy_id": args.strategy_id,
        "metrics": {},
        "latency_ms": None,
        "onnx_latency_ms": None,
        "onnx_path": None,
        "params": None,
        "loss_curve": [],
        "training_log_path": None,
        "error_trace": None,
        "duration_sec": 0.0,
        "tier_applied": {
            "epochs": tier.get("epochs"),
            "data_ratio": tier.get("data_ratio"),
        },
    }

    onnx_path = out_path.parent / "model.onnx"
    onnx_latency_path = out_path.parent / "onnx_latency.json"
    ckpt_path_default = out_path.parent / "ckpt.pt"

    # Step 1: git apply (if not baseline)
    if args.diff != "baseline":
        _log(f"git apply {args.diff}")
        rc, _, err = _run(["git", "apply", args.diff], cwd=worktree)
        if rc != 0:
            result["error_trace"] = f"git apply failed:\n{err}"
            _finish(result, out_path)

    # Step 2: adapter train
    train_cmd = [sys.executable, str(runner), "train",
                 "--output", str(ckpt_path_default)]
    if tier.get("epochs") is not None:
        train_cmd += ["--epochs", str(tier["epochs"])]
    if tier.get("data_ratio") is not None:
        train_cmd += ["--data-ratio", str(tier["data_ratio"])]

    _log(f"adapter train: {' '.join(train_cmd)}")
    t0 = time.time()
    rc, out, err = _run(train_cmd, cwd=worktree, env=env)
    result["duration_sec"] = time.time() - t0

    if rc != 0:
        result["error_trace"] = f"adapter train failed (rc={rc}):\n{err[-2000:]}"
        _finish(result, out_path)

    train_payload = _parse_stdout_json(out)
    if train_payload is None:
        result["error_trace"] = f"adapter train stdout not JSON:\n{out[-2000:]}"
        _finish(result, out_path)

    actual_ckpt = train_payload.get("checkpoint") or str(ckpt_path_default)
    result["metrics"].update(train_payload.get("metrics", {}))
    result["loss_curve"] = train_payload.get("loss_curve", [])
    result["params"] = train_payload.get("params")
    if train_payload.get("duration_sec"):
        result["duration_sec"] = train_payload["duration_sec"]

    # Step 3: adapter evaluate
    _log(f"adapter evaluate: ckpt={actual_ckpt}")
    eval_cmd = [sys.executable, str(runner), "evaluate",
                "--checkpoint", actual_ckpt]
    rc, out, err = _run(eval_cmd, cwd=worktree, env=env)
    if rc != 0:
        result["error_trace"] = f"adapter evaluate failed (rc={rc}):\n{err[-2000:]}"
        _finish(result, out_path)

    eval_payload = _parse_stdout_json(out)
    if eval_payload:
        result["metrics"].update(eval_payload.get("metrics", {}))
        result["latency_ms"] = eval_payload.get("latency_ms")
        if result["params"] is None:
            result["params"] = eval_payload.get("params")

    # Status OK if we reached here
    result["status"] = "ok"
    result["error_trace"] = None

    # Step 4: ONNX export (non-blocking)
    _log(f"export_onnx: ckpt={actual_ckpt}")
    export_cmd = [
        sys.executable, str(helpers / "export_onnx.py"),
        "--checkpoint", actual_ckpt,
        "--out", str(onnx_path),
        "--model-dir", str(worktree),
    ]
    rc, _, err = _run(export_cmd, cwd=worktree, env=env)
    if rc != 0:
        _log(f"ONNX export failed (non-blocking): {err[-500:]}")
    else:
        result["onnx_path"] = str(onnx_path)

        # Step 5: ONNX latency
        _log("measure_onnx_latency")
        latency_cmd = [
            sys.executable, str(helpers / "measure_onnx_latency.py"),
            "--onnx", str(onnx_path),
            "--out", str(onnx_latency_path),
            "--model-dir", str(worktree),
        ]
        rc, _, err = _run(latency_cmd, cwd=worktree, env=env)
        if rc != 0:
            _log(f"ONNX latency failed (non-blocking): {err[-500:]}")
        else:
            try:
                latency_payload = json.loads(Path(onnx_latency_path).read_text())
                result["onnx_latency_ms"] = latency_payload.get("latency_ms_median")
            except (json.JSONDecodeError, FileNotFoundError):
                pass

    _finish(result, out_path)


def _run(cmd, cwd=None, env=None, timeout=3600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd, env=env, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def _parse_stdout_json(stdout):
    """Parse last non-empty line of stdout as JSON."""
    lines = [l for l in stdout.splitlines() if l.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def _log(msg):
    print(f"[run_strategy] {msg}", file=sys.stderr)


def _finish(result, out_path):
    """Write eval_result.json, emit summary, exit with appropriate code."""
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({
        "status": result["status"],
        "out_path": str(out_path),
        "strategy_id": result.get("strategy_id"),
        "error": result.get("error_trace"),
    }))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
