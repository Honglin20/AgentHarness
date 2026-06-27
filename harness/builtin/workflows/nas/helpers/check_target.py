#!/usr/bin/env python
"""check_target.py — deterministic 达标判断 (validator 调用).

读 candidates / budget / metrics / baseline，输出 target_met + abort_recommended.
LLM 不参与判断 — 这是事实来源.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Deterministic target-reach checker")
    p.add_argument("--candidates", required=True, help="path to candidates.json")
    p.add_argument("--budget", required=True, help="path to budget.json")
    p.add_argument("--metrics", required=True, help="path to metrics.json")
    p.add_argument("--baseline", required=True, help="path to baseline.json")
    args = p.parse_args()

    candidates = _load_json(args.candidates) or []
    budget = _load_json(args.budget)
    metrics = _load_json(args.metrics)
    baseline = _load_json(args.baseline)

    if not candidates:
        result = {
            "target_met": False,
            "best_strategy_id": None,
            "best_fitness": None,
            "best_metrics": None,
            "best_latency_ms": None,
            "primary_metric": metrics.get("primary_metric"),
            "primary_direction": None,
            "primary_drop": None,
            "checks": {"acc_constraint_met": False, "latency_constraint_met": False},
            "candidates_count": 0,
            "abort_recommended": True,
            "reason": "no candidates yet",
        }
        print(json.dumps(result, indent=2))
        return

    best = max(candidates, key=lambda c: c.get("fitness", 0.0))
    primary_name = metrics.get("primary_metric", "acc")
    primary_dir = _lookup_direction(metrics, primary_name)

    baseline_primary = _lookup_metric_value(baseline, primary_name)
    best_primary = best.get("metrics", {}).get(primary_name)
    if best_primary is None:
        best_primary = best.get("metrics", {}).get(primary_name)

    if baseline_primary is None or best_primary is None:
        primary_drop = None
        acc_constraint = False
    elif primary_dir == "higher":
        denom = baseline_primary if baseline_primary != 0 else 1e-9
        primary_drop = max(0.0, (baseline_primary - best_primary) / abs(denom))
        acc_constraint = primary_drop <= budget.get("acc_tolerance", 0.0)
    else:
        denom = baseline_primary if baseline_primary != 0 else 1e-9
        primary_drop = max(0.0, (best_primary - baseline_primary) / abs(denom))
        acc_constraint = primary_drop <= budget.get("acc_tolerance", 0.0)

    target_latency = budget.get("target_latency_ms", float("inf"))
    best_latency = best.get("latency_ms")
    latency_constraint = bool(best_latency is not None and best_latency <= target_latency)

    target_met = bool(acc_constraint and latency_constraint)
    abort = _detect_abort(candidates)

    result = {
        "target_met": target_met,
        "best_strategy_id": best.get("strategy_id"),
        "best_fitness": best.get("fitness"),
        "best_metrics": best.get("metrics", {}),
        "best_latency_ms": best_latency,
        "primary_metric": primary_name,
        "primary_direction": primary_dir,
        "primary_drop": primary_drop,
        "checks": {
            "acc_constraint_met": acc_constraint,
            "latency_constraint_met": latency_constraint,
        },
        "candidates_count": len(candidates),
        "abort_recommended": abort,
        "reason": (
            f"best_fitness={best.get('fitness'):.4f}, "
            f"acc_drop={primary_drop}, target_met={target_met}, abort={abort}"
        ),
    }
    print(json.dumps(result, indent=2))


def _load_json(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text() or "null")
    except json.JSONDecodeError:
        return None


def _lookup_direction(metrics: dict, name: str) -> str:
    for m in metrics.get("metrics", []):
        if m.get("name") == name:
            return m.get("direction", "higher")
    return "higher"


def _lookup_metric_value(baseline: dict, name: str):
    if not baseline:
        return None
    return baseline.get("metrics", {}).get(name, baseline.get(name))


def _detect_abort(candidates: list[dict]) -> bool:
    """Abort heuristic: 最近 5 个 strategy 的 max fitness 不在末位（最近无提升）."""
    if len(candidates) < 5:
        return False
    sorted_c = sorted(candidates, key=lambda c: c.get("iter_num", 0))
    recent = sorted_c[-5:]
    fitnesses = [c.get("fitness", 0.0) for c in recent]
    max_idx = fitnesses.index(max(fitnesses))
    return max_idx < 3  # 最大值在前 3 位 → 最近 2 个无提升


if __name__ == "__main__":
    main()
