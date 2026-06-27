#!/usr/bin/env python
"""project_memory.py — L1 project memory 读写 + lineage 重建.

L1 是 per-project、跨 session 共享的演化记忆：
    workflows/nas/memory/<project_name>/
        candidates.json     # 跨 session top-K 候选集
        lineage.json        # 演化树 (parent chain)
        experience.md       # summarizer 综合，给 planner
        cognition.md        # 累积的 RAG 检索结果
        dedup.idx           # motivation hash 去重
        meta.json           # created_at, last_session_id

接口:
    init_project_memory(project_name) -> dict           # 创建/初始化
    add_candidate(project_name, candidate) -> bool      # 追加
    get_candidates(project_name, tier_filter=None) -> list
    append_experience(project_name, entry) -> bool      # 追加 experience.md
    append_cognition(project_name, entry) -> bool
    is_motivation_dup(project_name, motivation_hash) -> bool
    record_motivation(project_name, motivation_hash) -> bool

原子写 + 简单文件锁（fcntl.flock）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _memory_root() -> Path:
    """L1 root: workflows/nas/memory/"""
    return Path(__file__).resolve().parent.parent / "memory"


def _project_dir(project_name: str) -> Path:
    return _memory_root() / project_name


def init_project_memory(project_name: str, source_session_dir: Optional[str] = None) -> dict:
    """Initialize L1 project memory. Idempotent.

    If source_session_dir is provided, attempt to import its candidates.json.
    Returns: {project_name, path, created_at, imported_count}
    """
    pdir = _project_dir(project_name)
    pdir.mkdir(parents=True, exist_ok=True)

    meta_path = pdir / "meta.json"
    candidates_path = pdir / "candidates.json"
    lineage_path = pdir / "lineage.json"
    experience_path = pdir / "experience.md"
    cognition_path = pdir / "cognition.md"
    dedup_path = pdir / "dedup.idx"

    # Idempotent: only init if absent
    if not candidates_path.exists():
        _atomic_write(candidates_path, "[]")
    if not lineage_path.exists():
        _atomic_write(lineage_path, json.dumps({"nodes": [], "edges": []}, indent=2))
    if not experience_path.exists():
        _atomic_write(experience_path, f"# Project Memory: {project_name}\n\nCross-session accumulated experience. Summarizer writes here.\n\n")
    if not cognition_path.exists():
        _atomic_write(cognition_path, f"# Cognition: {project_name}\n\nAccumulated RAG retrieval results across sessions.\n\n")
    if not dedup_path.exists():
        _atomic_write(dedup_path, "")

    # Update meta
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}
    meta["project_name"] = project_name
    meta["path"] = str(pdir)
    meta["last_updated"] = datetime.now().isoformat()
    meta.setdefault("created_at", datetime.now().isoformat())
    if source_session_dir:
        meta["last_source_session"] = source_session_dir
    _atomic_write(meta_path, json.dumps(meta, indent=2, ensure_ascii=False))

    return {
        "project_name": project_name,
        "path": str(pdir),
        "created_at": meta.get("created_at"),
        "imported_count": 0,
    }


def add_candidate(project_name: str, candidate: dict) -> bool:
    """Append a candidate to L1 candidates.json. Idempotent on strategy_id."""
    pdir = _project_dir(project_name)
    if not pdir.exists():
        init_project_memory(project_name)
    cands_path = pdir / "candidates.json"

    with _file_lock(cands_path):
        try:
            existing = json.loads(cands_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

        # Idempotent: skip if strategy_id exists
        sid = candidate.get("strategy_id")
        if sid and any(c.get("strategy_id") == sid for c in existing):
            return True

        existing.append(candidate)
        _atomic_write(cands_path, json.dumps(existing, indent=2, ensure_ascii=False))
    return True


def get_candidates(project_name: str, tier_filter: Optional[list[str]] = None) -> list[dict]:
    """Get all candidates, optionally filtered by tier."""
    pdir = _project_dir(project_name)
    cands_path = pdir / "candidates.json"
    if not cands_path.exists():
        return []
    try:
        cands = json.loads(cands_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if tier_filter:
        cands = [c for c in cands if c.get("tier", "T1") in tier_filter]
    return cands


def append_experience(project_name: str, entry: dict) -> bool:
    """Append a markdown-formatted entry to experience.md."""
    pdir = _project_dir(project_name)
    if not pdir.exists():
        init_project_memory(project_name)
    path = pdir / "experience.md"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n## [{ts}] {entry.get('event', 'unknown')}\n"
    for k, v in entry.items():
        if k == "event":
            continue
        block += f"- **{k}**: {v}\n"
    block += "\n"

    with path.open("a") as f:
        f.write(block)
    return True


def append_cognition(project_name: str, entry: dict) -> bool:
    """Append a RAG retrieval result to cognition.md."""
    pdir = _project_dir(project_name)
    if not pdir.exists():
        init_project_memory(project_name)
    path = pdir / "cognition.md"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n## [{ts}] {entry.get('query', 'unknown')[:80]}\n"
    for hit in entry.get("hits", []):
        block += f"- **[{hit.get('score', 0)}] {hit.get('id', '?')}** (domain={hit.get('domain', '?')}): {hit.get('technique', '?')}\n"
        block += f"  - Symptom: {hit.get('symptom', '?')}\n"
        block += f"  - Impl: {hit.get('implementation_guide', '?')[:200]}\n"
    block += "\n"

    with path.open("a") as f:
        f.write(block)
    return True


def motivation_hash(motivation: str) -> str:
    """Compute normalized hash of motivation text (lowercased, whitespace-collapsed)."""
    normalized = " ".join(motivation.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def is_motivation_dup(project_name: str, motivation: str) -> bool:
    """Check if motivation is duplicated (exact hash match in L1 dedup.idx)."""
    pdir = _project_dir(project_name)
    dedup_path = pdir / "dedup.idx"
    if not dedup_path.exists():
        return False
    h = motivation_hash(motivation)
    existing = dedup_path.read_text().splitlines()
    return h in existing


def record_motivation(project_name: str, motivation: str) -> bool:
    """Record motivation hash in L1 dedup.idx."""
    pdir = _project_dir(project_name)
    if not pdir.exists():
        init_project_memory(project_name)
    dedup_path = pdir / "dedup.idx"
    h = motivation_hash(motivation)
    with _file_lock(dedup_path):
        with dedup_path.open("a") as f:
            f.write(h + "\n")
    return True


# ---- Internal helpers ----

def _atomic_write(path: Path, content: str) -> None:
    """tmpfile + os.replace for atomic write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


class _file_lock:
    """Simple fcntl.flock-based file lock (context manager). macOS/Linux only."""
    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def __enter__(self):
        try:
            import fcntl
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self.fd = open(lock_path, "w")
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError) as e:
            # Non-fatal: log + proceed without lock (single-process case)
            print(f"[project_memory] WARNING: flock failed ({e}); proceeding without lock", file=sys.stderr)
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            try:
                import fcntl
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            self.fd.close()


def sync_iter_candidates(project: str, iter_dir: Path,
                        parent_id: str, primary_metric: str) -> dict:
    """Scan <iter_dir>/optimizer_*/{eval_result,fitness}.json + push to L1.

    Deterministic replacement for analyzer.md Step 5 bash loop. Eliminates
    LLM bash fragility (placeholders like <N>, <primary_metric>, etc.).
    """
    iter_num = int(iter_dir.name.split("_")[1])
    sources = ["hyperparam", "structural", "business"]
    pushed = []
    skipped = []
    for src in sources:
        opt_dir = iter_dir / f"optimizer_{src}"
        eval_path = opt_dir / "eval_result.json"
        fit_path = opt_dir / "fitness.json"
        if not eval_path.exists() or not fit_path.exists():
            skipped.append({"source": src, "reason": "missing eval/fitness"})
            continue
        try:
            eval_r = json.loads(eval_path.read_text())
            fitness = json.loads(fit_path.read_text())
        except json.JSONDecodeError as e:
            skipped.append({"source": src, "reason": f"json error: {e}"})
            continue

        # eval_result.json shape varies: may have top-level metrics, or {metrics: {...}}
        metrics = eval_r.get("metrics") or {
            k: v for k, v in eval_r.items()
            if isinstance(v, (int, float)) and k not in ("fitness",)
        }

        candidate = {
            "strategy_id": f"iter_{iter_num}_opt_{src}",
            "source": src,
            "source_dir": str(opt_dir),
            "parent_id": parent_id,
            "metrics": metrics,
            "fitness": fitness.get("fitness", 0.0),
            "fitness_components": fitness.get("fitness_components", {}),
            "tier": "T1",
            "t1_metric": metrics.get(primary_metric),
            "iter_num": iter_num,
        }
        ok = add_candidate(project, candidate)
        pushed.append({"source": src, "strategy_id": candidate["strategy_id"],
                       "fitness": candidate["fitness"], "added": ok})
    return {"pushed": pushed, "skipped": skipped, "iter_num": iter_num}


# ---- CLI ----

def main() -> None:
    p = argparse.ArgumentParser(description="L1 project_memory IO")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--project", required=True)
    p_init.add_argument("--source-session", default=None)

    p_add = sub.add_parser("add-candidate")
    p_add.add_argument("--project", required=True)
    p_add.add_argument("--candidate-json", required=True, help="JSON string or path")

    p_get = sub.add_parser("get-candidates")
    p_get.add_argument("--project", required=True)
    p_get.add_argument("--tier", nargs="+", default=None)

    p_exp = sub.add_parser("append-experience")
    p_exp.add_argument("--project", required=True)
    p_exp.add_argument("--event", required=True)
    p_exp.add_argument("--data-json", required=True, help="JSON dict of extra fields")

    p_dup = sub.add_parser("check-dup")
    p_dup.add_argument("--project", required=True)
    p_dup.add_argument("--motivation", required=True)

    # Deterministic batch helper: scan iter dir + push all optimizer fitnesses
    # to L1 candidates.json. Removes LLM bash-fragility (analyzer Step 5).
    p_sync = sub.add_parser("sync-iter-candidates")
    p_sync.add_argument("--project", required=True)
    p_sync.add_argument("--iter-dir", required=True,
                        help="path to <session_dir>/iter_<N>")
    p_sync.add_argument("--parent-id", required=True,
                        help="parent strategy_id (from selector)")
    p_sync.add_argument("--primary-metric", required=True,
                        help="primary metric name from metric_contract")

    args = p.parse_args()

    if args.cmd == "init":
        result = init_project_memory(args.project, args.source_session)
        print(json.dumps(result, indent=2))
    elif args.cmd == "add-candidate":
        if Path(args.candidate_json).exists():
            cand = json.loads(Path(args.candidate_json).read_text())
        else:
            cand = json.loads(args.candidate_json)
        ok = add_candidate(args.project, cand)
        print(json.dumps({"ok": ok}, indent=2))
    elif args.cmd == "get-candidates":
        cands = get_candidates(args.project, tier_filter=args.tier)
        print(json.dumps({"count": len(cands), "candidates": cands}, indent=2, ensure_ascii=False))
    elif args.cmd == "append-experience":
        data = json.loads(args.data_json)
        ok = append_experience(args.project, {"event": args.event, **data})
        print(json.dumps({"ok": ok}, indent=2))
    elif args.cmd == "check-dup":
        is_dup = is_motivation_dup(args.project, args.motivation)
        print(json.dumps({"is_dup": is_dup}, indent=2))
    elif args.cmd == "sync-iter-candidates":
        result = sync_iter_candidates(
            args.project, Path(args.iter_dir),
            args.parent_id, args.primary_metric)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
