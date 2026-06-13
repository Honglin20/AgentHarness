#!/usr/bin/env python
"""history.py — HISTORY.md (L1 索引) + iter_N/SUMMARY.md (L2 简述) 读写.

Subcommands:
  write-summary    --session --iter --parent --ok-count --failed-count
                     --best-fitness --best-id --insight --tier
  append-history   --session --iter --parent --best-fitness --summary-link
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

    args = p.parse_args()

    if args.cmd == "write-summary":
        result = _write_summary(args)
        print(json.dumps(result))
    elif args.cmd == "append-history":
        result = _append_history(args)
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


if __name__ == "__main__":
    main()
