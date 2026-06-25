#!/usr/bin/env python
"""candidate_selector.py — 分桶采样：elite + diversity.

对齐 ASI-Arch 论文 (pipeline/database/interface.py:29-30) 的做法：
    parent = sample_from_range(1, 10, 1)   # elite top 1-10 取 1 parent
    refs   = sample_from_range(11, 50, 4)  # diversity top 11-50 取 4 ref

NAS 落地版本：
    - elite 桶: tier ∈ {T1, T2_passed}（T2_failed 不进 elite）
    - diversity 桶: top 11-50（含 T2_failed 防重复探索）
    - rotation rule: 禁止同 source 连续 3 轮被选为 parent

接口:
    sample_parent_and_refs(candidates, elite_k=10, ref_k=4, last_sources=[]) -> dict
    CLI:
        python candidate_selector.py sample --candidates-json <path> --last-sources hyperparam structural
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any


def _eligible_for_elite(c: dict) -> bool:
    """Elite bucket: tier in {T1, T2_passed} (legacy tier=unset treated as T1)."""
    tier = c.get("tier", "T1")
    return tier in ("T1", "T2_passed", None)


def sample_parent_and_refs(
    candidates: list[dict],
    elite_k: int = 10,
    ref_k: int = 4,
    last_sources: list[str] | None = None,
    baseline: dict | None = None,
    seed: int | None = None,
) -> dict:
    """Sample parent + refs from candidates via bucket sampling.

    Args:
        candidates: L1 + L2 merged candidates (list of dicts with at least 'score', 'source', 'tier')
        elite_k: elite bucket size (top-N by score)
        ref_k: number of reference candidates
        last_sources: list of sources selected in recent iters (for rotation rule)
        baseline: virtual baseline entry (used as parent when no candidates eligible)
        seed: random seed

    Returns:
        {
            "parent": <candidate dict or baseline virtual>,
            "refs": [<up to ref_k candidates>],
            "rotation_rule_applied": bool,
            "elite_bucket_size": int,
            "diversity_bucket_size": int,
            "rationale": str
        }
    """
    if seed is not None:
        random.seed(seed)

    # Sort all by score desc (default 0 if missing)
    sorted_all = sorted(candidates, key=lambda c: c.get("score", c.get("fitness", 0.0)), reverse=True)

    # Split into elite (eligible only) and diversity (all incl. T2_failed)
    elite_pool = [c for c in sorted_all if _eligible_for_elite(c)][:elite_k]
    diversity_pool = sorted_all[elite_k:elite_k + 40]  # next 40 (may contain T2_failed)

    # First iter: no candidates → return baseline virtual
    if not elite_pool and baseline is None:
        return {
            "parent": None,
            "refs": [],
            "rotation_rule_applied": False,
            "elite_bucket_size": 0,
            "diversity_bucket_size": 0,
            "rationale": "no candidates and no baseline provided",
        }

    if not elite_pool:
        # Fallback to baseline virtual
        parent = baseline
        rationale = "no eligible elite candidates; using baseline as parent"
        rotation_rule_applied = False
    else:
        # Pick parent: prefer top-1 unless rotation rule triggers
        top1 = elite_pool[0]
        rotation_rule_applied = False

        if last_sources and len(last_sources) >= 2:
            # Check if same source was used in last 2 iters
            last_two = last_sources[-2:]
            if len(set(last_two)) == 1 and last_two[0] == top1.get("source"):
                # Try to find an alternative in elite
                alt = next((c for c in elite_pool[1:] if c.get("source") != top1.get("source")), None)
                if alt is not None:
                    parent = alt
                    rotation_rule_applied = True
                    rationale = f"rotation: top1 source={top1.get('source')} would be 3rd in a row; picked {alt.get('strategy_id')}"
                else:
                    parent = top1
                    rationale = f"top1 by score (no alternative source in elite for rotation)"
            else:
                parent = top1
                rationale = f"top1 by score: {top1.get('strategy_id')}"
        else:
            parent = top1
            rationale = f"top1 by score: {top1.get('strategy_id')}"

    # Sample refs from diversity pool
    refs = random.sample(diversity_pool, min(ref_k, len(diversity_pool))) if diversity_pool else []

    return {
        "parent": parent,
        "refs": refs,
        "rotation_rule_applied": rotation_rule_applied,
        "elite_bucket_size": len(elite_pool),
        "diversity_bucket_size": len(diversity_pool),
        "rationale": rationale,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Bucket-based candidate sampling")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sample = sub.add_parser("sample")
    p_sample.add_argument("--candidates-json", required=True, help="Path to candidates.json")
    p_sample.add_argument("--elite-k", type=int, default=10)
    p_sample.add_argument("--ref-k", type=int, default=4)
    p_sample.add_argument("--last-sources", nargs="*", default=[], help="Sources selected in recent iters")
    p_sample.add_argument("--seed", type=int, default=None)
    p_sample.add_argument("--out", default=None)

    args = p.parse_args()

    if args.cmd == "sample":
        cands = json.loads(Path(args.candidates_json).read_text())
        result = sample_parent_and_refs(
            candidates=cands,
            elite_k=args.elite_k,
            ref_k=args.ref_k,
            last_sources=args.last_sources,
            seed=args.seed,
        )
        out = json.dumps(result, indent=2, ensure_ascii=False, default=str)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(out)
        print(out)


if __name__ == "__main__":
    main()
