#!/usr/bin/env python
"""direction.py — plateau 检测 + 方向推荐 + 已探索方向记录.

Subcommands:
  detect-plateau    --session --window [--write]
  suggest-direction --session --domain-insights
  mark-explored     --session --iter --directions <json> [--best-fitness]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Plateau + direction tracking")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_plateau = sub.add_parser("detect-plateau")
    p_plateau.add_argument("--session", required=True)
    p_plateau.add_argument("--window", type=int, default=3)
    p_plateau.add_argument("--write", default=None)

    p_suggest = sub.add_parser("suggest-direction")
    p_suggest.add_argument("--session", required=True)
    p_suggest.add_argument("--domain-insights", required=True)

    p_mark = sub.add_parser("mark-explored")
    p_mark.add_argument("--session", required=True)
    p_mark.add_argument("--iter", type=int, required=True)
    p_mark.add_argument("--directions", required=True,
                        help="JSON list of {tag, description} or strings")
    p_mark.add_argument("--best-fitness", type=float, default=0.0)

    args = p.parse_args()

    if args.cmd == "detect-plateau":
        result = _detect_plateau(args.session, args.window)
        if args.write:
            Path(args.write).write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    elif args.cmd == "suggest-direction":
        result = _suggest_direction(args.session, args.domain_insights)
        print(json.dumps(result, indent=2))
    elif args.cmd == "mark-explored":
        result = _mark_explored(args.session, args.iter,
                                json.loads(args.directions), args.best_fitness)
        print(json.dumps(result))


def _load_candidates(session: str) -> list[dict]:
    p = Path(session) / "candidates.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text() or "[]")
    except json.JSONDecodeError:
        return []


def _detect_plateau(session: str, window: int) -> dict:
    cands = _load_candidates(session)
    if not cands:
        return {
            "plateau": False,
            "recent_fitness": [],
            "fitness_std": 0.0,
            "reason": "no candidates yet",
        }

    iter_best: dict[int, float] = {}
    for c in cands:
        it = c.get("iter_num", 0)
        f = c.get("fitness", 0.0)
        if it not in iter_best or f > iter_best[it]:
            iter_best[it] = f

    sorted_iters = sorted(iter_best.keys())
    if len(sorted_iters) < window:
        return {
            "plateau": False,
            "recent_fitness": [iter_best[i] for i in sorted_iters],
            "fitness_std": 0.0,
            "reason": f"only {len(sorted_iters)} iters (< window={window})",
        }

    recent = [iter_best[i] for i in sorted_iters[-window:]]
    std = statistics.stdev(recent) if len(recent) > 1 else 0.0
    mean = statistics.mean(recent)
    cv = std / (abs(mean) + 1e-9)

    recent_max = max(recent)
    historical_iters = sorted_iters[:-window]
    if historical_iters:
        historical_max = max(iter_best[i] for i in historical_iters)
        no_improvement = (
            historical_max > 0
            and recent_max <= historical_max * 1.01
        )
    else:
        historical_max = None
        no_improvement = False

    # Plateau triggers if EITHER:
    # - low_variance: cv < 0.08 (recent best fitness barely changes)
    # - no_improvement: recent window didn't break historical best by >1%
    low_variance = cv < 0.08
    plateau = low_variance or no_improvement

    reasons = []
    if low_variance:
        reasons.append(f"cv={cv:.4f} < 0.08 (low variance)")
    if no_improvement:
        reasons.append(
            f"recent_max={recent_max:.4f} ≤ historical_max*1.01="
            f"{historical_max * 1.01:.4f} (no record break)"
        )

    return {
        "plateau": plateau,
        "recent_fitness": recent,
        "fitness_std": std,
        "fitness_cv": cv,
        "recent_max": recent_max,
        "historical_max": historical_max,
        "window": window,
        "reason": " + ".join(reasons) if reasons else f"cv={cv:.4f}, exploring",
    }


def _load_directions(session: str) -> list[dict]:
    p = Path(session) / "direction.md"
    if not p.exists():
        return []
    content = p.read_text()
    explored = []
    current_iter = None
    for line in content.splitlines():
        m = re.match(r"## iter (\d+)", line)
        if m:
            current_iter = int(m.group(1))
        elif line.strip().startswith("- direction:") and current_iter is not None:
            tag_part = line.split("direction:", 1)[1].strip()
            tag = tag_part.split("—")[0].strip()
            explored.append({"iter": current_iter, "tag": tag})
    return explored


def _suggest_direction(session: str, domain_insights_path: str) -> dict:
    explored = _load_directions(session)
    explored_tags = {e["tag"] for e in explored}

    insights_p = Path(domain_insights_path)
    insights = insights_p.read_text() if insights_p.exists() else ""
    suggested = []

    in_recommended = False
    for line in insights.splitlines():
        if re.search(r"推荐.*方向|Recommended.*Directions", line, re.IGNORECASE):
            in_recommended = True
            continue
        if in_recommended:
            if line.startswith("#"):
                break
            stripped = line.strip()
            if stripped.startswith("-"):
                tag_part = stripped.lstrip("- ").split(":")[0].split("—")[0].strip()
                if tag_part and tag_part not in explored_tags:
                    suggested.append({"tag": tag_part, "description": stripped})

    plateau = _detect_plateau(session, 3)
    direction_change = bool(
        plateau.get("plateau")
        or len(explored_tags) >= 5
    )

    return {
        "direction_change": direction_change,
        "reason": (
            f"plateau={plateau.get('plateau')} "
            f"explored_count={len(explored_tags)} "
            f"(trigger: plateau OR explored>=5)"
        ),
        "suggested_directions": suggested[:5],
        "explored_count": len(explored_tags),
        "explored_tags": sorted(explored_tags),
    }


def _mark_explored(session: str, iter_num: int,
                   directions: list, best_fitness: float) -> dict:
    p = Path(session) / "direction.md"
    if not p.exists():
        p.write_text("# Directions Explored\n\n")

    with p.open("a") as f:
        f.write(f"\n## iter {iter_num}\n")
        for d in directions:
            if isinstance(d, str):
                tag, desc = d, d
            else:
                tag = d.get("tag", "unknown")
                desc = d.get("description", tag)
            f.write(
                f"- direction: {tag} — {desc} — "
                f"explored, best_fitness={best_fitness:.4f}\n"
            )

    return {"status": "ok", "marked": len(directions), "iter": iter_num}


if __name__ == "__main__":
    main()
