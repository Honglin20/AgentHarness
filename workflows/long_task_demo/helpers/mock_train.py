#!/usr/bin/env python3
"""Mock training script for long_task_demo.

Demonstrates the contract a real training script should follow so the harness
can observe progress and collect metrics:

  1. Accept --steps / --out_dir / --progress_file flags
  2. Periodically write progress to --progress_file (UI heartbeat surfaces this)
  3. Write metrics.json to --out_dir on completion
  4. Support --measure-only for separate latency measurement

No GPU, no model, no real training — just simulates the I/O contract so the
demo workflow can run on any machine in ~30s. Real training scripts (e.g.
projects/mnist/train.py) should adopt the same --progress_file / --out_dir
convention to plug into launch_task's heartbeat UX.

Usage:
    python mock_train.py --steps 30 --out_dir _demo_out --progress_file _demo_out/progress.json
    python mock_train.py --measure-only --out_dir _demo_out
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Mock training script")
    p.add_argument("--steps", type=int, default=30, help="number of training steps")
    p.add_argument("--out_dir", required=True, help="output directory for metrics")
    p.add_argument(
        "--progress_file",
        default=None,
        help="path to write progress JSON (read by harness heartbeat)",
    )
    p.add_argument(
        "--measure-only",
        action="store_true",
        help="skip training; just write latency.json and exit",
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Latency-only mode ────────────────────────────────────────────
    if args.measure_only:
        time.sleep(0.5)  # simulate model load + warmup
        latency_ms = 12.3
        throughput_qps = 81.3
        (out_dir / "latency.json").write_text(
            json.dumps(
                {"latency_ms": latency_ms, "throughput_qps": throughput_qps}
            )
        )
        print(f"latency_ms={latency_ms} throughput_qps={throughput_qps}")
        return 0

    # ── Training mode ────────────────────────────────────────────────
    progress_path = Path(args.progress_file) if args.progress_file else None
    if progress_path:
        progress_path.parent.mkdir(parents=True, exist_ok=True)

    for step in range(1, args.steps + 1):
        time.sleep(1.0)  # 1s per step — simulates compute
        loss = 1.0 / (step ** 0.5)  # fake decreasing loss

        if progress_path:
            progress_path.write_text(
                json.dumps(
                    {
                        "step": step,
                        "total_steps": args.steps,
                        "loss": round(loss, 4),
                        "epoch": max(1, step // 10),
                        "total_epochs": max(1, args.steps // 10),
                    }
                )
            )
        print(f"step={step}/{args.steps} loss={loss:.4f}")

    final_loss = round(1.0 / (args.steps ** 0.5), 4)
    final_acc = round(0.5 + 0.4 * (1 - 1.0 / (args.steps ** 0.5)), 4)
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                "final_loss": final_loss,
                "final_acc": final_acc,
                "steps": args.steps,
            }
        )
    )
    print(
        f"training done. final_loss={final_loss} final_acc={final_acc} "
        f"→ {out_dir}/metrics.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
