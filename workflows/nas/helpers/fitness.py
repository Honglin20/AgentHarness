#!/usr/bin/env python
"""fitness.py — 多维 fitness 计算 (judger 调用).

公式 (base):
  primary_normalized = (val - baseline) / baseline           if direction == "higher"
                     = (baseline - val) / baseline           if direction == "lower"
  acc_drop       = max(0, -primary_normalized)
  latency_ratio  = target_latency_ms / strategy_latency_ms
  param_ratio    = strategy_params / baseline_params
  stability      = 1 - normalize(std(loss_curve_tail))

  base_fitness = 0.4 * max(0, 1 - acc_drop / acc_tolerance)
              + 0.3 * min(1.5, latency_ratio)
              + 0.2 * (1 - param_ratio)
              + 0.1 * stability

Bonus (P3):
  target_hit_bonus = 0.1 if (manifest.hypothesis_type != "parametric"
                            AND manifest.profile_target in baseline_profile.top_latency_layers)
                    else 0.0

  fitness = base_fitness + target_hit_bonus
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Multi-dimensional fitness computation")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_compute = sub.add_parser("compute")
    p_compute.add_argument("--metrics-json", required=True)
    p_compute.add_argument("--baseline-json", required=True)
    p_compute.add_argument("--strategy-result", required=True, help="path to eval_result.json")
    p_compute.add_argument("--target-latency", type=float, required=True)
    p_compute.add_argument("--acc-tolerance", type=float, required=True)
    p_compute.add_argument("--no-writeback", action="store_true",
                           help="don't write fitness back to strategy_result")
    p_compute.add_argument("--use-onnx-latency", action="store_true",
                           help="use strategy.onnx_latency_ms if present (falls back to latency_ms)")
    p_compute.add_argument("--manifest", default=None,
                           help="path to manifest.json (for hypothesis_type + profile_target)")
    p_compute.add_argument("--baseline-profile", default=None,
                           help="path to baseline_profile.json (for top_latency_layers)")

    args = p.parse_args()

    if args.cmd == "compute":
        metrics = _load_json(args.metrics_json)
        baseline = _load_json(args.baseline_json)
        strategy = _load_json(args.strategy_result)
        manifest = _load_json(args.manifest) if args.manifest else None
        profile = _load_json(args.baseline_profile) if args.baseline_profile else None

        if strategy is None:
            print(json.dumps({"error": "strategy_result not found"}))
            sys.exit(1)

        result = _compute(
            metrics, baseline, strategy,
            args.target_latency, args.acc_tolerance,
            args.use_onnx_latency, manifest, profile,
        )
        print(json.dumps(result, indent=2))

        if not args.no_writeback:
            strategy["fitness"] = result["fitness"]
            strategy["primary_normalized"] = result["primary_normalized"]
            strategy["fitness_components"] = result["components"]
            Path(args.strategy_result).write_text(json.dumps(strategy, indent=2))


def _load_json(path: str) -> dict | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _lookup_direction(metrics: dict, name: str) -> str:
    for m in metrics.get("metrics", []):
        if m.get("name") == name:
            return m.get("direction", "higher")
    return "higher"


def _lookup_metric_value(blob: dict, name: str):
    if not blob:
        return None
    return blob.get("metrics", {}).get(name, blob.get(name))


def _compute(metrics: dict, baseline: dict, strategy: dict,
             target_latency: float, acc_tolerance: float,
             use_onnx_latency: bool = False,
             manifest: dict | None = None,
             profile: dict | None = None) -> dict:
    manifest = manifest or {}
    profile = profile or {}

    primary_name = metrics.get("primary_metric", "acc")
    primary_dir = _lookup_direction(metrics, primary_name)

    baseline_primary = _lookup_metric_value(baseline, primary_name)
    strategy_primary = _lookup_metric_value(strategy, primary_name)

    if baseline_primary is None or strategy_primary is None:
        primary_normalized = 0.0
    elif primary_dir == "higher":
        denom = baseline_primary if baseline_primary != 0 else 1e-9
        primary_normalized = (strategy_primary - baseline_primary) / abs(denom)
    else:
        denom = baseline_primary if baseline_primary != 0 else 1e-9
        primary_normalized = (baseline_primary - strategy_primary) / abs(denom)

    acc_drop = max(0.0, -primary_normalized)

    strategy_latency = strategy.get("latency_ms") or 0.0
    if use_onnx_latency:
        # Prefer onnx latency when available — more stable & cross-device comparable.
        # Fall back to pytorch latency if onnx not measured (e.g. export failed).
        strategy_latency = strategy.get("onnx_latency_ms") or strategy_latency
    latency_ratio = (target_latency / strategy_latency) if strategy_latency > 0 else 0.0

    baseline_params = baseline.get("params", 0) if baseline else 0
    strategy_params = strategy.get("params", baseline_params)
    if baseline_params > 0:
        param_ratio = strategy_params / baseline_params
    else:
        param_ratio = 1.0

    loss_curve = strategy.get("loss_curve") or []
    if len(loss_curve) >= 5:
        tail = loss_curve[-min(10, len(loss_curve)):]
        std = statistics.stdev(tail) if len(tail) > 1 else 0.0
        mean = statistics.mean(tail) if tail else 0.0
        stability = max(0.0, 1.0 - std / (abs(mean) + 1e-9))
    else:
        stability = 0.5

    acc_term = max(0.0, 1.0 - acc_drop / acc_tolerance) if acc_tolerance > 0 else 0.0
    base_fitness = (
        0.4 * acc_term
        + 0.3 * min(1.5, latency_ratio)
        + 0.2 * (1.0 - min(1.0, param_ratio))
        + 0.1 * stability
    )

    # Target-hit bonus: structural hypothesis hitting profile top-K latency layer
    hypothesis_type = manifest.get("hypothesis_type", "")
    profile_target = manifest.get("profile_target")
    top_layer_names = [
        l.get("name") for l in profile.get("top_latency_layers", []) if l.get("name")
    ]
    target_hit = bool(
        hypothesis_type
        and hypothesis_type != "parametric"
        and profile_target
        and profile_target in top_layer_names
    )
    target_hit_bonus = 0.1 if target_hit else 0.0

    fitness = base_fitness + target_hit_bonus

    return {
        "fitness": fitness,
        "primary_normalized": primary_normalized,
        "components": {
            "acc_drop": acc_drop,
            "latency_ratio": latency_ratio,
            "param_ratio": param_ratio,
            "stability": stability,
            "acc_term": acc_term,
            "base_fitness": base_fitness,
            "target_hit": target_hit,
            "target_hit_bonus": target_hit_bonus,
        },
        "primary_metric": primary_name,
        "primary_direction": primary_dir,
    }


if __name__ == "__main__":
    main()
