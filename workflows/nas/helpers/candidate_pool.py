#!/usr/bin/env python
"""candidate_pool.py — elite pool CRUD (top-K strategy maintenance).

Subcommands:
  init   --session <dir>                              # 初始化空 candidates.json
  push   --session <dir> --iter N --ranking <json>    # 加入本轮 ok strategy，原子保留 top-K
  top    --session <dir> --k N                        # 取 top-N
  list   --session <dir>                              # 列全部
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_TOP_K = 10


def main() -> None:
    p = argparse.ArgumentParser(description="Elite pool CRUD")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--session", required=True)

    p_push = sub.add_parser("push")
    p_push.add_argument("--session", required=True)
    p_push.add_argument("--iter", type=int, required=True)
    p_push.add_argument("--ranking", required=True, help="JSON list of strategy results")
    p_push.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_push.add_argument(
        "--top-k-per-type", type=int, default=0,
        help="if >0, retain at most N per hypothesis_type within --top-k "
             "(guarantees elite pool has slot for each of parametric/structural_local/structural_global)",
    )

    p_top = sub.add_parser("top")
    p_top.add_argument("--session", required=True)
    p_top.add_argument("--k", type=int, default=5)

    p_list = sub.add_parser("list")
    p_list.add_argument("--session", required=True)

    args = p.parse_args()

    if args.cmd == "init":
        _atomic_write(_path(args.session), "[]")
        print(json.dumps({"status": "ok", "initialized": True, "path": str(_path(args.session))}))
    elif args.cmd == "push":
        ranking = json.loads(args.ranking)
        result = _push(args.session, args.iter, ranking, args.top_k, args.top_k_per_type)
        print(json.dumps(result, indent=2))
    elif args.cmd == "top":
        cands = _load(args.session)
        cands.sort(key=lambda c: c.get("fitness", 0.0), reverse=True)
        print(json.dumps(cands[: args.k], indent=2))
    elif args.cmd == "list":
        print(json.dumps(_load(args.session), indent=2))


def _path(session: str) -> Path:
    return Path(session) / "candidates.json"


def _load(session: str) -> list[dict]:
    p = _path(session)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text() or "[]")
    except json.JSONDecodeError:
        return []


def _atomic_write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, p)


def _select_top_k_per_type(
    candidates: list[dict], total_cap: int, per_type_cap: int
) -> list[dict]:
    """Retain at most per_type_cap per hypothesis_type, capped at total_cap.

    Iterates candidates in their existing (fitness-desc) order, accepts each
    candidate iff its type's running count is below per_type_cap. Stops when
    total_cap is reached. Guarantees elite pool spreads slots across
    parametric / structural_local / structural_global instead of letting one
    type crowd out the others.
    """
    type_counts: dict[str, int] = {}
    result: list[dict] = []
    for c in candidates:
        if len(result) >= total_cap:
            break
        t = c.get("hypothesis_type", "parametric")
        if type_counts.get(t, 0) >= per_type_cap:
            continue
        result.append(c)
        type_counts[t] = type_counts.get(t, 0) + 1
    return result


def _push(
    session: str,
    iter_num: int,
    ranking: list[dict],
    top_k: int,
    top_k_per_type: int = 0,
) -> dict:
    existing = _load(session)
    for r in ranking:
        entry = {
            "strategy_id": r.get("strategy_id"),
            "parent_strategy_id": r.get("parent_strategy_id"),
            "iter_num": iter_num,
            "fitness": r.get("fitness", 0.0),
            "metrics": r.get("metrics", {}),
            "latency_ms": r.get("latency_ms"),
            "params": r.get("params"),
            "diff_path": r.get("diff_path"),
            "hypothesis": r.get("hypothesis"),
            "hypothesis_type": r.get("hypothesis_type", "parametric"),
            "domain_basis": r.get("domain_basis"),
            "direction_tag": r.get("direction_tag"),
            "tier_applied": r.get("tier_applied"),
        }
        existing.append(entry)
    existing.sort(key=lambda c: c.get("fitness", 0.0), reverse=True)

    if top_k_per_type > 0:
        new_list = _select_top_k_per_type(existing, top_k, top_k_per_type)
    else:
        new_list = existing[:top_k]

    truncated_count = max(0, len(existing) - len(new_list))
    _atomic_write(_path(session), json.dumps(new_list, indent=2))
    return {
        "status": "ok",
        "pushed": len(ranking),
        "total_after": len(new_list),
        "truncated": truncated_count,
        "type_distribution": _type_distribution(new_list),
    }


def _type_distribution(candidates: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in candidates:
        t = c.get("hypothesis_type", "parametric")
        counts[t] = counts.get(t, 0) + 1
    return counts


if __name__ == "__main__":
    main()
