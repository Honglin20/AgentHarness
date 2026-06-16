#!/usr/bin/env python
"""run_strategy.py — Run a NAS strategy end-to-end.

Wraps: cd worktree → git apply diff → adapter train → adapter evaluate →
export_onnx (subprocess) → measure_onnx_latency (subprocess).

Used by trainer/refiner sub_agents to eliminate task template duplication.
Writes eval_result.json to --out path.

Adapter is loaded via importlib as a unique module (per-call) to avoid
sys.modules cache poisoning when trainer runs multiple strategies in the
same Python process. Worktree is added to sys.path[0] and set as cwd so
the adapter's user-code imports (`from model import Net`) resolve.

Exit code: 0 if status="ok", 1 otherwise.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worktree", default=".",
                   help="working dir for git apply + adapter calls. Default '.' (=current cwd). "
                        "When invoked by sub_agent with isolation='worktree', this is the worktree path.")
    p.add_argument("--diff", required=True,
                   help="path to .patch, or 'baseline' to skip git apply")
    p.add_argument("--adapter-path", dest="adapter_path", required=True,
                   help="path to _nas_adapter.py")
    p.add_argument("--tier", default="null",
                   help='JSON: {"epochs": N} or null for single-tier (user default)')
    p.add_argument("--out", required=True,
                   help="eval_result.json output path")
    p.add_argument("--helpers-dir", dest="helpers_dir", required=True)
    p.add_argument("--strategy-id", dest="strategy_id", default=None)
    p.add_argument("--gpu-id", dest="gpu_id", default=None)
    p.add_argument(
        "--model-override-path", dest="model_override_path", default=None,
        help="path to new model .py file for structural_global strategies "
             "(planner hypothesizes new architecture; Coder writes the .py; "
             "adapter.get_model dynamically loads it via importlib)",
    )
    p.add_argument(
        "--model-override-class", dest="model_override_class", default=None,
        help="class name to import from --model-override-path (required iff path is set)",
    )
    args = p.parse_args()

    tier_raw = json.loads(args.tier)  # {"epochs": N} | None
    tier = tier_raw or {}
    worktree = Path(args.worktree).resolve()
    adapter_path = Path(args.adapter_path).resolve()
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
        },
    }

    onnx_path = out_path.parent / "model.onnx"
    onnx_latency_path = out_path.parent / "onnx_latency.json"
    ckpt_path_default = out_path.parent / "ckpt.pt"
    actual_ckpt = str(ckpt_path_default)  # default; updated after train

    # Step 1: git apply (if not baseline)
    if args.diff != "baseline":
        _log(f"git apply {args.diff}")
        rc, _, err = _run(["git", "apply", args.diff], cwd=worktree)
        if rc != 0:
            result["error_trace"] = f"git apply failed:\n{err}"
            _finish(result, out_path)

    # Steps 2-3: load adapter, train, evaluate (in adapter's cwd context)
    try:
        with _load_adapter(adapter_path, worktree, args.strategy_id) as adapter:
            # Step 2: adapter train
            _log(f"adapter train: epochs={tier.get('epochs')}")
            t0 = time.time()
            # structural_global override: planner hypothesized a new model file;
            # adapter.get_model dynamically loads it instead of _construct_model.
            get_model_kwargs: dict = {}
            if args.model_override_path:
                if not args.model_override_class:
                    result["error_trace"] = (
                        "--model-override-path set without --model-override-class; "
                        "structural_global requires both"
                    )
                    _finish(result, out_path)
                get_model_kwargs["model_override_path"] = args.model_override_path
                get_model_kwargs["model_override_class"] = args.model_override_class
                _log(f"using model override: {args.model_override_path}::{args.model_override_class}")
            model = adapter.get_model(**get_model_kwargs)
            train_result = adapter.train(
                model,
                epochs=tier.get("epochs"),
                output=ckpt_path_default,
            )
            result["duration_sec"] = time.time() - t0

            if not train_result.get("ok"):
                result["error_trace"] = (
                    f"adapter train failed:\n{train_result.get('error', '')[-2000:]}"
                )
                _finish(result, out_path)

            actual_ckpt = (
                train_result.get("checkpoint")
                or str(ckpt_path_default)
            )
            result["metrics"].update(train_result.get("metrics", {}))
            result["loss_curve"] = train_result.get("loss_curve", [])
            result["params"] = train_result.get("params")
            if train_result.get("duration_sec"):
                result["duration_sec"] = train_result["duration_sec"]

            # Step 3: adapter evaluate
            _log(f"adapter evaluate: ckpt={actual_ckpt}")
            eval_result = adapter.evaluate(model, checkpoint=actual_ckpt)
            if eval_result.get("ok"):
                result["metrics"].update(eval_result.get("metrics", {}))
                result["latency_ms"] = eval_result.get("latency_ms")
                if result["params"] is None:
                    result["params"] = eval_result.get("params")
            else:
                _log(
                    f"adapter evaluate failed (non-blocking): "
                    f"{eval_result.get('error', '')[-500:]}"
                )
    except Exception as e:
        import traceback
        result["error_trace"] = (
            f"adapter load/execute failed:\n"
            f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        )
        _finish(result, out_path)

    # Status OK if we reached here
    result["status"] = "ok"
    result["error_trace"] = None

    # Step 4: ONNX export (non-blocking, subprocess to helpers — unchanged)
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


@contextmanager
def _load_adapter(adapter_path: Path, worktree: Path, strategy_id: str | None = None):
    """Load _nas_adapter.py as a unique module; cleanup sys.path/cwd/modules on exit.

    Each call generates a unique module name (keyed on worktree id + strategy_id)
    to avoid sys.modules cache poisoning when trainer runs multiple strategies
    in the same Python process. Worktree is added to sys.path[0] and set as cwd
    so the adapter's user-code imports (`from model import Net`) resolve.
    """
    suffix = strategy_id or worktree.name
    module_name = f"_nas_adapter_{id(worktree)}_{suffix}"

    worktree_str = str(worktree)
    sys.path.insert(0, worktree_str)
    original_cwd = os.getcwd()
    os.chdir(worktree)

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(adapter_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load adapter spec from {adapter_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module  # register before exec for self-refs
        spec.loader.exec_module(module)
        yield module
    finally:
        os.chdir(original_cwd)
        if worktree_str in sys.path:
            sys.path.remove(worktree_str)
        sys.modules.pop(module_name, None)


def _run(cmd, cwd=None, env=None, timeout=3600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd, env=env, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


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
