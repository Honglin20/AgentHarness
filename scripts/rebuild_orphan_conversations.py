#!/usr/bin/env python
"""One-shot: rebuild truncated main record conversation from iter sidecars.

Background: ``server/runner.py`` historically projected main record's
``conversation`` field from the Bus buffer (FIFO 2000). Long runs evicted
early events, leaving runs like 847ab064 with a truncated conversation that
showed only the last agent's tool calls in the UI.

This script scans every run record on disk, detects truncation by comparing
main record conversation size against the total tool_calls available in iter
sidecars, and rewrites the conversation field using
``rebuild_conversation_from_sidecars`` when sidecars have more data.

Usage:
    python scripts/rebuild_orphan_conversations.py --dry-run
    python scripts/rebuild_orphan_conversations.py
    python scripts/rebuild_orphan_conversations.py --run-id <uuid>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is importable when run as a script
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.paths import get_runs_dir  # noqa: E402
from harness.persistence.conversation_rebuild import rebuild_conversation_from_sidecars  # noqa: E402


def _is_sidecar(filename: str) -> bool:
    """Filter out sidecar files — only main run records qualify."""
    return any(suffix in filename for suffix in (
        "+charts", "+events", "+outline", "+snapshot",
        "+iter_index", "+iters+", "+conversation",
    ))


def _count_sidecar_tool_calls(run_id: str) -> tuple[int, int]:
    """Return (total_tool_calls_across_sidecars, num_sidecar_files).

    Reads iter_index to enumerate (node, iter) pairs, then counts tool_calls
    in each sidecar. Returns (0, 0) when iter_index or all sidecars are absent.
    """
    from harness.run_store import get_run_store
    store = get_run_store()
    iter_index = store.get_iter_index(run_id) or {}
    total_calls = 0
    num_files = 0
    for node_id, entries in iter_index.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            iter_num = entry.get("iter")
            if not isinstance(iter_num, int):
                continue
            sidecar = store.get_iter_sidecar(run_id, node_id, iter_num)
            if sidecar is None:
                continue
            num_files += 1
            calls = sidecar.get("tool_calls") or []
            if isinstance(calls, list):
                total_calls += len(calls)
    return total_calls, num_files


def _count_conversation_tool_calls(conversation: list) -> int:
    """Count tool_call messages in a conversation list."""
    if not isinstance(conversation, list):
        return 0
    return sum(1 for m in conversation if isinstance(m, dict) and m.get("type") == "tool_call")


def _rewrite_main_record(path: Path, conversation: list) -> None:
    """Atomic rewrite of main record's conversation field."""
    raw = path.read_text()
    record = json.loads(raw)
    record["conversation"] = conversation
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
    import os
    os.replace(str(tmp), str(path))


def process_run(path: Path, *, dry_run: bool) -> str:
    """Process one run record. Returns status string for logging.

    Statuses:
      - "skip:no_sidecars"  — iter sidecars absent, nothing to rebuild from
      - "skip:complete"     — conversation already has >= sidecar tool_calls
      - "fixed:N<M"         — rewrote from N to M messages
      - "error:..."         — exception during processing
    """
    try:
        record = json.loads(path.read_text())
    except Exception as e:
        return f"error:read:{e}"

    run_id = record.get("run_id")
    if not run_id:
        return "skip:no_run_id"

    sidecar_calls, num_sidecar_files = _count_sidecar_tool_calls(run_id)
    if num_sidecar_files == 0:
        return "skip:no_sidecars"

    conv_calls = _count_conversation_tool_calls(record.get("conversation"))
    if conv_calls >= sidecar_calls:
        return f"skip:complete ({conv_calls}>={sidecar_calls})"

    agent_io = record.get("agent_io") or {}
    rebuilt = rebuild_conversation_from_sidecars(run_id, agent_io)
    if not rebuilt:
        return "error:rebuild_empty"

    rebuilt_calls = _count_conversation_tool_calls(rebuilt)
    if rebuilt_calls <= conv_calls:
        return f"skip:rebuild_not_better ({rebuilt_calls}<={conv_calls})"

    if dry_run:
        return f"would_fix: {conv_calls}->{rebuilt_calls} tool_calls (run={run_id})"

    try:
        _rewrite_main_record(path, rebuilt)
    except Exception as e:
        return f"error:write:{e}"

    return f"fixed: {conv_calls}->{rebuilt_calls} tool_calls (run={run_id})"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Report only, don't rewrite")
    p.add_argument("--run-id", help="Process only this run id (otherwise scan all)")
    args = p.parse_args()

    runs_dir = get_runs_dir()
    if args.run_id:
        targets = [runs_dir / f"{args.run_id}.json"]
        if not targets[0].exists():
            print(f"ERROR: run record not found: {targets[0]}", file=sys.stderr)
            return 1
    else:
        targets = sorted(
            f for f in runs_dir.glob("*.json")
            if not _is_sidecar(f.name)
        )

    print(f"Scanning {len(targets)} run record(s) in {runs_dir}")
    print(f"Mode: {'dry-run' if args.dry_run else 'write'}")
    print()

    fixed = 0
    skipped = 0
    errors = 0
    for path in targets:
        status = process_run(path, dry_run=args.dry_run)
        if status.startswith("fixed") or status.startswith("would_fix"):
            fixed += 1
            print(f"  {path.name}: {status}")
        elif status.startswith("error"):
            errors += 1
            print(f"  {path.name}: {status}")
        else:
            skipped += 1

    print()
    print(f"Summary: {fixed} fixed, {skipped} skipped, {errors} errors")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
