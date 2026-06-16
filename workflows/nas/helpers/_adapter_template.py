#!/usr/bin/env python
"""NAS Adapter — auto-generated from workflows/nas/helpers/_adapter_template.py.

Contract boundary between NAS workflow and the user project. NAS trainers /
refiners call these 4 public functions; they NEVER directly invoke user
train.py / evaluate.py / training_command.

Public API (NAS team maintains, do not edit unless changing contract):
    get_model(**overrides) -> nn.Module
    train(model, epochs=None, output=None) -> dict
    evaluate(model, checkpoint=None) -> dict
    export_onnx(model, out_path) -> str

Placeholder functions (adapter_generator fills, keep signatures stable):
    _construct_model(**overrides) -> nn.Module    [MODEL_IMPORT]
    _train_impl(model, epochs, output) -> dict    [TRAIN_WRAPPER]
    _eval_impl(model, checkpoint) -> dict         [EVAL_WRAPPER]

Re-generate by re-running scout's adapter_generator sub_agent.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn


_ADAPTER_TEMPLATE_VERSION = "1.1"  # bumped from 1.0: get_model supports model_override_path

# ═══════════════════════════════════════════════════════════════════════
# Configuration — adapter_generator fills these constants at gen time
# ═══════════════════════════════════════════════════════════════════════

# Absolute path to NAS helpers dir (export_onnx.py / measure_onnx_latency.py).
HELPERS_DIR = Path("{{HELPERS_DIR}}")

# User's weights file. "NOT_FOUND" if no weights detected.
WEIGHTS_PATH = "{{WEIGHTS_PATH}}"

# Dummy inputs for latency measurement / ONNX export.
# Format: {"shape": [1, 1, 28, 28], "dtype": "float32"}
# None if not declared in workflow inputs AND adapter_generator failed to probe.
DUMMY_INPUTS_VALUE: dict | None = None


# ═══════════════════════════════════════════════════════════════════════
# PLACEHOLDER FUNCTIONS — adapter_generator replaces each function body
# ═══════════════════════════════════════════════════════════════════════
#
# Instructions for adapter_generator (LLM):
#   - Read <session_dir>/project_analysis.json for model_class / train_entry / eval_entry
#   - Replace each function BODY (keep signature stable)
#   - Default body raises NotImplementedError — must be replaced

def _construct_model(**overrides) -> nn.Module:
    """MODEL_IMPORT placeholder.

    Implementation guidance:
    - Import user model class: `from <model_module> import <model_class>`
    - Instantiate with model_init_args from project_analysis:
        kwargs = {"hidden": 128, "layers": 3}
        kwargs.update(overrides)
        return Net(**kwargs)
    - Do NOT load weights here (get_model handles that via WEIGHTS_PATH)
    - Return raw nn.Module
    """
    raise NotImplementedError("MODEL_IMPORT placeholder not filled by adapter_generator")


def _train_impl(model: nn.Module, epochs: int | None, output: Path | None) -> dict:
    """TRAIN_WRAPPER placeholder.

    Implementation guidance:
    - Call user train function: `from <train_module> import <train_func>`
    - If epochs is not None: pass to user (via flag / arg / config patching)
    - If epochs is None: run user's default epochs (do NOT pass --epochs)
    - If output is not None: write checkpoint to output path; if user hardcodes
      path, report actual path in result["checkpoint"]
    - Capture metrics + loss_curve from: function return value (preferred),
      stdout regex, OR metrics file written by user script
    - Return: {"metrics": {...}, "loss_curve": [...], "checkpoint": "<actual or None>"}

    epochs_control_mechanism (from project_analysis) decides how to pass epochs:
    - cli_flag: subprocess + --epochs flag
    - function_arg: call function with epochs kwarg
    - config_file: patch config file temporarily, restore after
    - hardcoded: ignore epochs param, run user default
    """
    raise NotImplementedError("TRAIN_WRAPPER placeholder not filled by adapter_generator")


def _eval_impl(model: nn.Module, checkpoint: Path | None) -> dict:
    """EVAL_WRAPPER placeholder.

    Implementation guidance:
    - checkpoint arg: weights already loaded into model by evaluate() wrapper; can be None
    - If project_analysis.eval_entry exists: call user eval function
        `from <eval_module> import <eval_func>; metrics = eval_func(model, ...)`
    - If eval_entry is NOT_FOUND: build minimal inference loop
        loader = <load eval data>; correct = 0; total = 0
        with torch.no_grad(): for x, y in loader: ...
        metrics = {"acc": correct/total}  # or {} if no eval data
    - Do NOT measure latency here (evaluate wrapper handles via _measure_latency)
    - Return: {"metrics": {...}}

    evaluate_source modes (based on eval_entry):
    - subprocess: call evaluate.py as subprocess
    - in_train: call train.py --eval-only mode
    - metrics_file: read metrics.json written by training
    - checkpoint_only: load ckpt + dummy inference (no real eval data)
    """
    raise NotImplementedError("EVAL_WRAPPER placeholder not filled by adapter_generator")


# ═══════════════════════════════════════════════════════════════════════
# Public API — NAS team maintains; do not edit
# ═══════════════════════════════════════════════════════════════════════

def get_model(**overrides) -> nn.Module:
    """Instantiate user model + load weights if available. Returns model.eval().

    Callers: baseline_runner, trainer, refiner, adapter_generator smoke test.

    structural_global override: when called with `model_override_path` +
    `model_override_class` kwargs (passed by run_strategy.py for strategies
    whose manifest.hypothesis_type == "structural_global"), skips
    _construct_model and dynamically loads the user-provided new model
    file from worktree. Lets planner hypothesize brand-new architectures
    without Coder patching _construct_model body (adapter stays the
    NAS-team-maintained contract boundary).
    """
    override_path = overrides.pop("model_override_path", None)
    override_class = overrides.pop("model_override_class", None)
    if override_path:
        model = _load_override_model(override_path, override_class, overrides)
    else:
        model = _construct_model(**overrides)
    if WEIGHTS_PATH and WEIGHTS_PATH != "NOT_FOUND" and Path(WEIGHTS_PATH).exists():
        _load_state_dict(model, WEIGHTS_PATH)
    return model.eval()


def _load_override_model(
    path: str,
    class_name: str | None,
    overrides: dict,
) -> nn.Module:
    """Dynamically import a user-provided model from a .py file path.

    Used by structural_global strategies. Path may be absolute or relative;
    relative paths resolve against the adapter file's parent dir (= worktree
    root when run_strategy.py loads the adapter).

    Returns the instantiated model (caller handles weight loading + eval()).
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        raise FileNotFoundError(
            f"model_override_path not found: {p} (relative={path!r})"
        )
    module_id = f"_nas_override_{p.stem}_{id(p)}"
    spec = importlib.util.spec_from_file_location(module_id, str(p))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load override spec from {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not class_name:
        raise ValueError("model_override_class required when model_override_path is set")
    cls = getattr(mod, class_name, None)
    if cls is None:
        raise AttributeError(f"class {class_name!r} not found in {p}")
    return cls(**overrides)


def train(model: nn.Module, epochs: int | None = None, output=None) -> dict:
    """Train model for given epochs (None = user project default).

    Returns:
        {
          "ok": bool,
          "checkpoint": str | None,    # actual ckpt path
          "metrics": dict,              # e.g. {"acc": 0.85, "loss": 0.32}
          "loss_curve": list[float],    # per-epoch or per-step loss samples
          "params": int,                # total parameter count
          "duration_sec": float,
          "error": str | None,          # None on success; traceback on failure
        }

    Never raises — failures captured in result["ok"]=False + result["error"].
    """
    start = time.time()
    params = _safe_param_count(model)
    try:
        if epochs is not None:
            model.train()
        impl_result = _train_impl(model, epochs, Path(output) if output else None)
        return {
            "ok": True,
            "checkpoint": str(output) if output else impl_result.get("checkpoint"),
            "metrics": impl_result.get("metrics", {}),
            "loss_curve": impl_result.get("loss_curve", []),
            "params": params,
            "duration_sec": time.time() - start,
            "error": None,
        }
    except Exception as e:
        return _failure_result(start, params, e, is_eval=False)


def evaluate(model: nn.Module, checkpoint=None) -> dict:
    """Evaluate model (no retrain). Returns metrics + latency_ms + params.

    Returns:
        {
          "ok": bool,
          "metrics": dict,
          "latency_ms": float,         # median per-batch latency, 0.0 if unmeasurable
          "params": int,
          "duration_sec": float,
          "error": str | None,
        }

    Never raises.
    """
    start = time.time()
    params = _safe_param_count(model)
    try:
        if checkpoint is not None and Path(checkpoint).exists():
            _load_state_dict(model, str(checkpoint))
        model.eval()
        impl_result = _eval_impl(model, Path(checkpoint) if checkpoint else None)
        latency_ms = impl_result.get("latency_ms")
        if latency_ms is None:
            latency_ms = _measure_latency(model)
        return {
            "ok": True,
            "metrics": impl_result.get("metrics", {}),
            "latency_ms": latency_ms,
            "params": params,
            "duration_sec": time.time() - start,
            "error": None,
        }
    except Exception as e:
        return _failure_result(start, params, e, is_eval=True)


def export_onnx(model: nn.Module, out_path) -> str:
    """Export model to ONNX. Delegates to helpers/export_onnx.py.

    Raises RuntimeError on failure — caller (run_strategy.py) treats as non-blocking
    (ONNX export failure does not fail the strategy).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # export_onnx.py expects --checkpoint; write model state to temp file
    ckpt_path = out_path.parent / f"{out_path.stem}.nas_tmp_ckpt.pt"
    torch.save(model.state_dict(), ckpt_path)
    try:
        cmd = [
            sys.executable, str(HELPERS_DIR / "export_onnx.py"),
            "--checkpoint", str(ckpt_path),
            "--out", str(out_path),
            "--model-dir", str(Path(__file__).resolve().parent),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"export_onnx.py failed: {result.stderr[-500:]}")
        return str(out_path)
    finally:
        try:
            ckpt_path.unlink(missing_ok=True)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Helpers — NAS team maintains
# ═══════════════════════════════════════════════════════════════════════

def _safe_param_count(model: nn.Module) -> int:
    """Count params; returns 0 if model has no parameters (unusual but safe)."""
    try:
        return sum(p.numel() for p in model.parameters())
    except Exception:
        return 0


def _load_state_dict(model: nn.Module, weights_path: str) -> None:
    """Load weights from path. Handles common state_dict wrappings.

    Wrappers unwrapped: state_dict / model_state_dict / model / net.

    If shape mismatch occurs (e.g. NAS strategy mutated model architecture
    but weights_path points to pre-mutation baseline), warns + skips loading
    rather than raising — NAS strategies should train from scratch anyway.
    """
    state = torch.load(weights_path, map_location="cpu")
    if isinstance(state, dict):
        for wrapper_key in ("state_dict", "model_state_dict", "model", "net"):
            if wrapper_key in state and isinstance(state[wrapper_key], dict):
                state = state[wrapper_key]
                break
    try:
        model.load_state_dict(state)
    except RuntimeError as e:
        import sys
        sys.stderr.write(
            f"[nas_adapter] warning: load_state_dict failed ({type(e).__name__}); "
            f"likely architecture mutation by NAS strategy. Using random init.\n"
        )


def _measure_latency(model: nn.Module, n_warmup: int = 3, n_iter: int = 10) -> float:
    """Median per-batch latency in milliseconds.

    Returns 0.0 if DUMMY_INPUTS_VALUE is None (latency unmeasurable without dummy).
    """
    if not DUMMY_INPUTS_VALUE:
        return 0.0
    shape = list(DUMMY_INPUTS_VALUE.get("shape", []))
    if shape:
        shape[0] = 1  # batch=1 for latency measurement
    dtype_str = DUMMY_INPUTS_VALUE.get("dtype", "float32")
    dtype = getattr(torch, dtype_str, torch.float32)
    dummy = torch.zeros(shape, dtype=dtype) if shape else torch.zeros(1)
    device = next(model.parameters()).device
    dummy = dummy.to(device)
    model.eval()
    with torch.no_grad():
        for _ in range(n_warmup):
            model(dummy)
        times = []
        for _ in range(n_iter):
            t0 = time.perf_counter()
            model(dummy)
            times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[len(times) // 2] if times else 0.0


def _failure_result(start: float, params: int, exc: Exception, is_eval: bool) -> dict:
    """Build failure dict for train() / evaluate()."""
    import traceback
    base = {
        "ok": False,
        "params": params,
        "duration_sec": time.time() - start,
        "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
    }
    if is_eval:
        return {**base, "metrics": {}, "latency_ms": 0.0}
    return {**base, "checkpoint": None, "metrics": {}, "loss_curve": []}


# ═══════════════════════════════════════════════════════════════════════
# CLI entrypoint — manual smoke test: `python _nas_adapter.py smoke`
# ═══════════════════════════════════════════════════════════════════════

def _cli():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke")
    sub.add_parser("version")
    args = p.parse_args()

    if args.cmd == "version":
        print(f"adapter_template_version={_ADAPTER_TEMPLATE_VERSION}")
        return

    if args.cmd == "smoke":
        print("[smoke] get_model()...", flush=True)
        model = get_model()
        print(f"[smoke] model: {type(model).__name__}, params={_safe_param_count(model)}", flush=True)

        print("[smoke] train(epochs=1)...", flush=True)
        train_result = train(model, epochs=1)
        print(f"[smoke] train ok={train_result['ok']}, metrics={train_result['metrics']}", flush=True)
        if not train_result["ok"]:
            print(f"[smoke] train failed:\n{train_result['error']}", flush=True)
            sys.exit(1)

        print("[smoke] evaluate()...", flush=True)
        eval_result = evaluate(model)
        print(f"[smoke] eval ok={eval_result['ok']}, metrics={eval_result['metrics']}, "
              f"latency_ms={eval_result['latency_ms']:.3f}", flush=True)

        print("[smoke] export_onnx()...", flush=True)
        try:
            onnx_path = export_onnx(model, Path("_smoke_test.onnx"))
            print(f"[smoke] onnx exported: {onnx_path}", flush=True)
            Path("_smoke_test.onnx").unlink(missing_ok=True)
        except Exception as e:
            print(f"[smoke] onnx export failed (non-blocking): {e}", flush=True)

        print("[smoke] all done", flush=True)


if __name__ == "__main__":
    _cli()
