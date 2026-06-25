#!/usr/bin/env python
"""dispatch_train.py — universal training dispatcher for NAS adapters.

**Why this exists**: adapter_generator (LLM) rewrites `_nas_adapter.py` on
each session start. Without a single dispatch point, LLM tends to write
`subprocess.run(cmd, cwd=working_dir)` directly in `_train_impl`, bypassing
the backend abstraction (TRAIN_BACKEND env var) — breaking cloud training
for every project that gets adapter-regenerated.

**This module is the ONE place** that decides local vs ssh. Adapters call:

    from dispatch_train import dispatch_train
    result = dispatch_train(
        train_cmd=["python", "train.py", "--steps", "20", "--out_dir", out_dir],
        work_dir=Path(__file__).parent,
        log_path=log_path,
        env={"CUDA_VISIBLE_DEVICES": "0"},
    )
    # result.ok / result.exit_code / result.log_path / result.metrics_path

LLM-generated adapters cannot accidentally bypass this because the template
_inlines_ this exact call signature (adapter only fills `train_cmd`).

Backend selection (普适，所有 domain 适用):
    TRAIN_BACKEND env var: "local" (default) | "ssh"

For SSH backend, ensures ~/.nas/cloud.yaml `ssh:` section is set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Make train_backend importable when this helper is invoked from a project dir
_HELPERS_DIR = Path(__file__).resolve().parent
if str(_HELPERS_DIR) not in sys.path:
    sys.path.insert(0, str(_HELPERS_DIR))

from train_backend import get_backend, BackendResult, TrainBackend  # noqa: E402


def dispatch_train(
    *,
    train_cmd: list[str],
    work_dir: Path,
    log_path: Path,
    metrics_path: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
    backend_name: str | None = None,
) -> BackendResult:
    """Universal training dispatch. Adapters MUST use this (not subprocess.run).

    Args:
        train_cmd: argv list, e.g. ["python", "train.py", "--steps", "20"]
                   First "python" element is auto-replaced with remote_python
                   when using SSH backend.
        work_dir: working directory containing train.py + configs. For SSH,
                  this dir is rsynced to remote_project_dir/<work_dir.name>/.
        log_path: local path to write train.log (downloaded from remote if SSH)
        metrics_path: local path for metrics.json (downloaded from remote).
                      If None + train_cmd has --out_dir, metrics land there.
        env: extra env vars (CUDA_VISIBLE_DEVICES, HF_ENDPOINT, etc.)
        timeout: max wall-clock seconds
        backend_name: override; default reads TRAIN_BACKEND env

    Returns:
        BackendResult with .ok / .exit_code / .log_path / .metrics_path / .error
    """
    backend = get_backend(backend_name)
    # Always merge env with os.environ so callers don't have to forward every
    # relevant var (HF_ENDPOINT, NAS_TRAIN_BUDGET_STEPS, ASI_DATA_DIR, etc.)
    # This is the普适 default — if caller wants to exclude env, they pass empty dict.
    effective_env = dict(os.environ)
    if env:
        effective_env.update(env)
    result: BackendResult = backend.run(
        train_cmd=train_cmd,
        worktree=work_dir,
        env=effective_env,
        timeout=timeout,
        log_path=log_path,
        metrics_path=metrics_path,
    )
    return result


def make_env(**overrides: str) -> dict[str, str]:
    """Build env dict inheriting os.environ + overrides. Common usage:

        env = make_env(CUDA_VISIBLE_DEVICES="0",
                       HF_ENDPOINT=os.environ.get("HF_ENDPOINT", ""),
                       NAS_TRAIN_BUDGET_STEPS=os.environ.get("NAS_TRAIN_BUDGET_STEPS", ""))
    """
    env = dict(os.environ)
    env.update({k: str(v) for k, v in overrides.items() if v is not None})
    return env


if __name__ == "__main__":
    # CLI: anything after `--` is the train command (avoids argparse conflict
    # with train.py's own flags like --steps/--epochs).
    # Example:
    #   python dispatch_train.py --work-dir . --log train.log -- python train.py --steps 30
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--metrics", default=None)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("train_cmd", nargs=argparse.REMAINDER,
                   help="train command after '--', e.g. -- python train.py --steps 30")
    args = p.parse_args()
    # Strip leading "--" if present
    cmd = args.train_cmd[1:] if args.train_cmd and args.train_cmd[0] == "--" else args.train_cmd
    if not cmd:
        print("error: no train_cmd given. Usage: dispatch_train.py --work-dir . --log log -- python train.py ...",
              file=sys.stderr)
        sys.exit(2)
    r = dispatch_train(
        train_cmd=cmd,
        work_dir=Path(args.work_dir),
        log_path=Path(args.log),
        metrics_path=Path(args.metrics) if args.metrics else None,
        timeout=args.timeout,
    )
    print(f"ok={r.ok} exit={r.exit_code} backend={r.backend} "
          f"dur={r.duration_sec:.1f}s")
    if not r.ok:
        print(f"error: {r.error}")
        sys.exit(1)
