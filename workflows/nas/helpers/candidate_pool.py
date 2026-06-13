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
        result = _push(args.session, args.iter, ranking, args.top_k)
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


def _push(session: str, iter_num: int, ranking: list[dict], top_k: int) -> dict:
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
            "domain_basis": r.get("domain_basis"),
            "direction_tag": r.get("direction_tag"),
            "tier_applied": r.get("tier_applied"),
        }
        existing.append(entry)
    existing.sort(key=lambda c: c.get("fitness", 0.0), reverse=True)
    truncated_count = max(0, len(existing) - top_k)
    new_list = existing[:top_k]
    _atomic_write(_path(session), json.dumps(new_list, indent=2))
    return {
        "status": "ok",
        "pushed": len(ranking),
        "total_after": len(new_list),
        "truncated": truncated_count,
    }


if __name__ == "__main__":
    main()
