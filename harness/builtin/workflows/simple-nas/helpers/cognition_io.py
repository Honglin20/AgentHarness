#!/usr/bin/env python
"""cognition_io.py — L0 cognition_base 读写 + 关键词检索.

L0 是静态、全局共享的 SOTA recipe 库，按 domain 分文件：
    workflows/nas/cognition/<domain>/recipes.json

接口:
    load_recipes(domain) -> list[dict]
    search_recipes(domain, query, k=3) -> list[dict]  # 关键词匹配
    search_all_domains(query, k=3) -> list[dict]      # 跨 domain

CLI:
    python cognition_io.py search --domain cv --query "过拟合" --k 3
    python cognition_io.py list --domain cv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _cognition_root() -> Path:
    """L0 root: workflows/nas/cognition/"""
    return Path(__file__).resolve().parent.parent / "cognition"


def load_recipes(domain: str) -> list[dict]:
    """Load all recipes for a domain. Returns [] if domain file missing."""
    path = _cognition_root() / domain / "recipes.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("recipes", [])
    except (json.JSONDecodeError, OSError) as e:
        print(f"[cognition_io] WARNING: failed to load {path}: {e}", file=sys.stderr)
        return []


def list_domains() -> list[str]:
    """List all available domains in L0."""
    root = _cognition_root()
    if not root.exists():
        return []
    return sorted([d.name for d in root.iterdir() if d.is_dir() and (d / "recipes.json").exists()])


def _score_recipe(recipe: dict, query_lower: str, query_tokens: list[str]) -> int:
    """Score recipe by keyword overlap with query. Higher = better match."""
    tags = recipe.get("tags", [])
    if isinstance(tags, list):
        tags_str = " ".join(str(t) for t in tags)
    else:
        tags_str = str(tags)
    searchable = " ".join([
        str(recipe.get("symptom", "")),
        str(recipe.get("technique", "")),
        tags_str,
        str(recipe.get("applicable_task", "")),
    ]).lower()

    score = 0
    # Full query substring match (highest signal)
    if query_lower in searchable:
        score += 10
    # Token overlap
    for tok in query_tokens:
        if not tok:
            continue
        if tok in searchable:
            score += 2
    return score


def search_recipes(domain: str, query: str, k: int = 3) -> list[dict]:
    """Search recipes by keyword. Returns top-k matches sorted by relevance.

    Args:
        domain: e.g. 'cv', 'nlp', 'wireless'
        query: natural language query (e.g. "过拟合 数据量小")
        k: top-k results

    Returns:
        List of recipe dicts, each enriched with 'score' field.
    """
    recipes = load_recipes(domain)
    if not recipes:
        return []

    query_lower = query.lower().strip()
    query_tokens = query_lower.split()

    scored = []
    for r in recipes:
        s = _score_recipe(r, query_lower, query_tokens)
        if s > 0:
            enriched = {**r, "score": s}
            scored.append(enriched)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


def search_all_domains(query: str, k: int = 3) -> list[dict]:
    """Search across all domains. Returns top-k matches."""
    all_hits = []
    for domain in list_domains():
        hits = search_recipes(domain, query, k=k)
        for h in hits:
            h["domain"] = domain
            all_hits.append(h)
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:k]


def main() -> None:
    p = argparse.ArgumentParser(description="L0 cognition_base IO")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List domains or recipes in a domain")
    p_list.add_argument("--domain", default=None, help="If omitted, list domains")

    p_search = sub.add_parser("search", help="Search recipes by keyword")
    p_search.add_argument("--domain", default=None, help="Restrict to domain; omit for cross-domain")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--k", type=int, default=3)
    p_search.add_argument("--out", default=None, help="Write JSON to path instead of stdout")

    args = p.parse_args()

    if args.cmd == "list":
        if args.domain is None:
            result = {"domains": list_domains()}
        else:
            recipes = load_recipes(args.domain)
            result = {
                "domain": args.domain,
                "count": len(recipes),
                "recipes": [{"id": r.get("id"), "symptom": r.get("symptom"), "technique": r.get("technique")} for r in recipes],
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.cmd == "search":
        if args.domain:
            hits = search_recipes(args.domain, args.query, args.k)
        else:
            hits = search_all_domains(args.query, args.k)
        result = {"query": args.query, "domain": args.domain or "all", "hits": hits}
        out = json.dumps(result, indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(out)
        print(out)


if __name__ == "__main__":
    main()
