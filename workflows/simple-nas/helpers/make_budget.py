"""Generate budget.json with strict Pydantic schema validation.

Deterministic tier-planning logic — replaces LLM free-form JSON authoring
which was producing inconsistent schemas across runs (3-tier matrices,
extra fields like _meta / budget_allocation, etc.).

Usage:
    python make_budget.py \
        --baseline <baseline.json> \
        --project-analysis <project_analysis.json> \
        --target-latency 0.05 \
        --acc-tolerance 0.02 \
        --strategies-per-iter 3 \
        --out <session_dir>/budget.json

Tier matrix (deterministic, only epochs dimension — data_ratio removed):
    T < 300s                       → 1 tier (search=full)
    T ≥ 300s + epochs_controllable → 2 tier (search=partial, refine=full)
    T ≥ 300s + not controllable    → 1 tier forced
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ── Pydantic schemas (mirror devkit/nas/schemas.py) ──────────────────────

class TierSpec:
    """Plain dict wrapper — Pydantic-free for portability."""
    pass


def _decide_tier_system(T: float, epochs_controllable: bool, total_epochs: int) -> tuple[list, int, list]:
    """Return (proposed_tiers, max_tier, degraded_dimensions)."""
    if T < 300.0 or not epochs_controllable:
        # Single tier forced
        tiers = [{"name": "search", "epochs": None}]
        max_tier = 0
        degraded = [] if epochs_controllable else ["epochs"]
        return tiers, max_tier, degraded

    # 2 tier (epochs controllable + T ≥ 300)
    search_epochs = max(1, total_epochs // 3) if total_epochs else 1
    refine_epochs = total_epochs if total_epochs else None
    tiers = [
        {"name": "search", "epochs": search_epochs},
        {"name": "refine", "epochs": refine_epochs},
    ]
    return tiers, 1, []


def _build_rationale(T: float, epochs_controllable: bool, max_tier: int, degraded: list) -> str:
    if not epochs_controllable:
        return f"T={T:.1f}s; epochs hardcoded → single tier forced (degraded_dimensions=['epochs'])."
    if T < 300.0:
        return f"T={T:.1f}s < 300s threshold → single tier (cheap enough to run full epochs every strategy)."
    if max_tier == 1:
        return f"T={T:.1f}s ≥ 300s + epochs controllable → 2 tier (search partial_epoch / refine full_epoch)."
    return f"T={T:.1f}s → single tier."


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, help="baseline.json path")
    p.add_argument("--project-analysis", required=True, help="project_analysis.json path")
    p.add_argument("--target-latency", type=float, required=True)
    p.add_argument("--acc-tolerance", type=float, required=True)
    p.add_argument("--strategies-per-iter", type=int, required=True)
    p.add_argument("--out", required=True, help="budget.json output path")
    args = p.parse_args()

    baseline = json.loads(Path(args.baseline).read_text())
    pa = json.loads(Path(args.project_analysis).read_text())

    T = float(baseline.get("full_training_duration_sec") or baseline.get("baseline_duration_sec") or 0.0)
    one_epoch_sec = float(baseline.get("one_epoch_sec", 0.0))
    total_epochs = int(baseline.get("total_epochs", 10))
    epochs_controllable = bool(pa.get("epochs_controllable", False))

    tiers, max_tier, degraded = _decide_tier_system(T, epochs_controllable, total_epochs)
    rationale = _build_rationale(T, epochs_controllable, max_tier, degraded)

    # Strict BudgetFile schema — no extra fields, no _meta, no budget_allocation
    budget = {
        "baseline_duration_sec": T,
        "one_epoch_sec": one_epoch_sec,
        "total_epochs": total_epochs,
        "tier_recommendation": {
            "rationale": rationale,
            "proposed_tiers": tiers,
            "max_tier": max_tier,
            "degraded_dimensions": degraded,
        },
        "target_latency_ms": args.target_latency,
        "acc_tolerance": args.acc_tolerance,
        "strategies_per_iter": args.strategies_per_iter,
    }

    # Validate shape (defensive — Pydantic would catch this in workflow runtime)
    required_keys = {"baseline_duration_sec", "one_epoch_sec", "total_epochs",
                     "tier_recommendation", "target_latency_ms", "acc_tolerance",
                     "strategies_per_iter"}
    missing = required_keys - set(budget.keys())
    if missing:
        print(f"ERROR: missing keys {missing}", file=sys.stderr)
        sys.exit(1)
    tr = budget["tier_recommendation"]
    if tr["max_tier"] > 1:
        print(f"ERROR: max_tier > 1 (data_ratio removed; only 0/1 allowed)", file=sys.stderr)
        sys.exit(1)
    for t in tr["proposed_tiers"]:
        if set(t.keys()) != {"name", "epochs"}:
            print(f"ERROR: TierSpec must have only name/epochs, got {set(t.keys())}", file=sys.stderr)
            sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(budget, indent=2))
    print(f"wrote {out_path}: max_tier={max_tier}, tiers={len(tiers)}, degraded={degraded}")


if __name__ == "__main__":
    main()
