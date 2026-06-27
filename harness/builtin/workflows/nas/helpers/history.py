#!/usr/bin/env python
"""history.py — HISTORY.md (L1 索引) + iter_N/SUMMARY.md (L2 简述) + running_memory/ (L3 per-direction) 读写.

Subcommands:
  write-summary         --session --iter --parent --ok-count --failed-count
                         --best-fitness --best-id --insight --tier
  append-history        --session --iter --parent --best-fitness --summary-link
  write-running-memory  --session --direction --iter --changes --result --insight
                         (per-direction cross-iter memory for optimizers)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="HISTORY.md + SUMMARY.md writer")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_summary = sub.add_parser("write-summary")
    p_summary.add_argument("--session", required=True)
    p_summary.add_argument("--iter", type=int, required=True)
    p_summary.add_argument("--parent", required=True)
    p_summary.add_argument("--ok-count", type=int, required=True)
    p_summary.add_argument("--failed-count", type=int, required=True)
    p_summary.add_argument("--best-fitness", type=float, required=True)
    p_summary.add_argument("--best-id", required=True)
    p_summary.add_argument("--insight", required=True)
    p_summary.add_argument("--tier", default="")

    p_history = sub.add_parser("append-history")
    p_history.add_argument("--session", required=True)
    p_history.add_argument("--iter", type=int, required=True)
    p_history.add_argument("--parent", required=True)
    p_history.add_argument("--best-fitness", type=float, required=True)
    p_history.add_argument("--summary-link", required=True)

    p_rm = sub.add_parser("write-running-memory")
    p_rm.add_argument("--session", required=True)
    p_rm.add_argument("--direction", required=True,
                      help="hyperparam | structural | business")
    p_rm.add_argument("--iter", type=int, required=True)
    p_rm.add_argument("--changes", required=True,
                      help="One-line summary of changes tried")
    p_rm.add_argument("--result", required=True,
                      help="One-line summary of metric outcome")
    p_rm.add_argument("--insight", required=True,
                      help="What worked / what didn't / next hint")

    args = p.parse_args()

    if args.cmd == "write-summary":
        result = _write_summary(args)
        print(json.dumps(result))
    elif args.cmd == "append-history":
        result = _append_history(args)
        print(json.dumps(result))
    elif args.cmd == "write-running-memory":
        result = _write_running_memory(args)
        print(json.dumps(result))


def _write_summary(args) -> dict:
    iter_dir = Path(args.session) / f"iter_{args.iter}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    content = f"""# Iter {args.iter}

- Parent: {args.parent}
- Tier: {args.tier or "n/a"}
- Strategies: {args.ok_count} ok, {args.failed_count} failed
- Best fitness: {args.best_fitness:.4f} (strategy_id={args.best_id})
- Insight: {args.insight}
"""
    out = iter_dir / "SUMMARY.md"
    out.write_text(content)
    return {"status": "ok", "path": str(out)}


def _append_history(args) -> dict:
    p = Path(args.session) / "HISTORY.md"
    if not p.exists():
        p.write_text("# NAS Search History\n\n")

    line = (
        f"- iter {args.iter} | parent={args.parent} | "
        f"best_fitness={args.best_fitness:.4f} | "
        f"[summary]({args.summary_link})\n"
    )

    lines = p.read_text().splitlines()
    if len(lines) <= 2:
        p.write_text("# NAS Search History\n\n" + line)
    else:
        insert_idx = 0
        for i, l in enumerate(lines):
            if i > 0 and not l.strip():
                insert_idx = i + 1
                break
        if insert_idx == 0:
            insert_idx = 2
        new_lines = lines[:insert_idx] + [line.rstrip()] + lines[insert_idx:]
        p.write_text("\n".join(new_lines) + "\n")

    return {"status": "ok", "appended_to": str(p)}


def _write_running_memory(args) -> dict:
    """Append a per-direction memory entry to running_memory/optimizer_<direction>.md.

    File format:
        # Optimizer <Direction> Memory

        ## Iter <N>
        - Changes: <changes>
        - Result: <result>
        - Insight: <insight>

    Optimizers read this at the start of each iter to avoid repeating themselves.
    """
    valid_directions = {"hyperparam", "structural", "business"}
    if args.direction not in valid_directions:
        return {
            "status": "error",
            "reason": f"direction must be one of {valid_directions}, got {args.direction!r}",
        }

    rm_dir = Path(args.session) / "running_memory"
    rm_dir.mkdir(parents=True, exist_ok=True)
    rm_path = rm_dir / f"optimizer_{args.direction}.md"

    if not rm_path.exists():
        header = f"# Optimizer {args.direction.title()} Memory\n\n"
        header += (
            f"Cross-iter log of what this optimizer tried, what worked, what didn't.\n"
            f"Read at the start of each iter to avoid repeating failed experiments.\n\n"
        )
        rm_path.write_text(header)

    entry = (
        f"## Iter {args.iter}\n"
        f"- **Changes**: {args.changes}\n"
        f"- **Result**: {args.result}\n"
        f"- **Insight**: {args.insight}\n\n"
    )

    with rm_path.open("a") as f:
        f.write(entry)

    return {"status": "ok", "appended_to": str(rm_path), "iter": args.iter}


if __name__ == "__main__":
    main()
