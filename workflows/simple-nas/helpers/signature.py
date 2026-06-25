#!/usr/bin/env python
"""signature.py — strategy diff → 稳定 hash + 去重查询.

Subcommands:
  compute       --diff <path or content>
  check         --diff <path or content> --index <path>
  append-batch  --index <path> --strategies <json: [{strategy_id, diff_path}]>

签名 = hash(改了哪些文件 + 改造类型集合), 不含行级 diff.
捕获 intent 而非 exact content → 防止相同 idea 微调后被认为是新策略.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Strategy signature + dedup")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_compute = sub.add_parser("compute")
    p_compute.add_argument("--diff", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--diff", required=True)
    p_check.add_argument("--index", required=True)

    p_append = sub.add_parser("append-batch")
    p_append.add_argument("--index", required=True)
    p_append.add_argument("--strategies", required=True,
                          help="JSON list of {strategy_id, diff_path}")

    args = p.parse_args()

    if args.cmd == "compute":
        content = _read_diff(args.diff)
        sig = _compute_signature(content)
        print(json.dumps({"signature": sig}))

    elif args.cmd == "check":
        content = _read_diff(args.diff)
        sig = _compute_signature(content)
        entries = _load_index(args.index)
        for e in entries:
            if e.get("signature") == sig:
                print(json.dumps({
                    "duplicate": True,
                    "similar_to": e.get("strategy_id"),
                    "signature": sig,
                }, indent=2))
                return
        print(json.dumps({
            "duplicate": False,
            "similar_to": None,
            "signature": sig,
        }, indent=2))

    elif args.cmd == "append-batch":
        strategies = json.loads(args.strategies)
        result = _append_batch(args.index, strategies)
        print(json.dumps(result))


def _read_diff(arg: str) -> str:
    """arg can be a path or inline diff content."""
    p = Path(arg)
    if p.exists() and p.is_file():
        return p.read_text()
    return arg


def _compute_signature(diff_content: str) -> str:
    files: set[str] = set()
    ops: set[str] = set()

    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            files.add(line[6:].strip())
        elif line.startswith("--- a/"):
            f = line[6:].strip()
            if f != "/dev/null":
                files.add(f)
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            if re.search(r"\b(def |class |function )", content):
                ops.add("add_func")
            elif content.startswith(("import ", "from ")):
                ops.add("import_change")
            elif any(kw in content for kw in ("nn.", "torch.", "tf.", "jax.", "keras.")):
                ops.add("layer_change")
            elif re.search(r"(Linear|Conv|Attention|LayerNorm|Dropout|ReLU|GELU|Softmax)"
                           r"[\.\(]", content):
                ops.add("layer_change")
        elif line.startswith("-") and not line.startswith("---"):
            ops.add("removal")

    signature_input = json.dumps({"files": sorted(files), "ops": sorted(ops)},
                                 sort_keys=True)
    return hashlib.sha256(signature_input.encode()).hexdigest()[:16]


def _load_index(index_path: str) -> list[dict]:
    p = Path(index_path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _append_batch(index_path: str, strategies: list[dict]) -> dict:
    p = Path(index_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_index(index_path)
    existing_sigs = {e.get("signature") for e in existing}

    added = 0
    with p.open("a") as f:
        for s in strategies:
            diff_path = s.get("diff_path")
            if diff_path and Path(diff_path).exists():
                content = Path(diff_path).read_text()
            else:
                content = ""
            sig = _compute_signature(content)
            if sig in existing_sigs:
                continue
            entry = {"strategy_id": s.get("strategy_id"), "signature": sig}
            f.write(json.dumps(entry) + "\n")
            existing_sigs.add(sig)
            added += 1

    return {"status": "ok", "added": added, "total_unique": len(existing_sigs)}


if __name__ == "__main__":
    main()
