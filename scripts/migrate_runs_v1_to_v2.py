#!/usr/bin/env python3
"""migrate_runs_v1_to_v2 — optional migration for legacy run records.

Triggered when a user reports "old run can't see tool_calls / streaming".
NOT automatic — running this is an explicit operator choice.

What it does (per ADR §R4):
  1. Scans runs/ for v1 sidecars (missing tool_calls) + v1 snapshots
     (missing version field).
  2. If ``--dry-run`` (default): prints a migration plan, writes nothing.
  3. Otherwise:
     a. For each sidecar missing tool_calls: rebuild from events.json
        (scan agent.tool_call / agent.tool_result events for the
        matching node_id + iteration).
     b. Marks v1 snapshots with ``version: 1`` + ``migrated_at: <ts>``.
     c. Streaming snapshots are skipped (can't safely rebuild).

Idempotent: running twice produces identical output. Sidecars that
already have tool_calls are not touched.

Usage:
  python scripts/migrate_runs_v1_to_v2.py [--dry-run] [--run-id <id>] \\
      [--runs-dir runs]

Exit codes:
  0 — success (or dry-run complete)
  1 — error during migration (partial state possible; re-run is safe)
  2 — environment error (missing runs dir, etc.)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ITER_SIDECAR_RE = re.compile(
    r"^(?P<run_id>[a-zA-Z0-9_-]+)\+iters\+(?P<node_id>[a-zA-Z0-9_-]+)\+(?P<iter>\d+)\.json$"
)
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class MigrationPlan:
    """Per-run migration plan — what would be done if --dry-run is cleared."""

    run_id: str
    sidecars_needing_tool_calls: list[str] = field(default_factory=list)
    snapshots_needing_v1_marker: bool = False
    skipped_streaming: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        return bool(self.sidecars_needing_tool_calls or self.snapshots_needing_v1_marker)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save_atomic(path: Path, data: dict) -> None:
    """Atomic write — tmp + os.replace."""
    import os
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(str(tmp), str(path))


def _list_runs(runs_dir: Path) -> list[str]:
    run_ids: set[str] = set()
    for entry in runs_dir.iterdir():
        if not entry.is_file():
            continue
        m = _ITER_SIDECAR_RE.match(entry.name)
        if m:
            run_ids.add(m.group("run_id"))
            continue
        for suffix in ("+iter_index.json", "+snapshot.json", "+outline.json",
                       "+charts.json", "+events.json", ".json"):
            if entry.name.endswith(suffix):
                cand = entry.name[:-len(suffix)]
                if _SAFE_ID_RE.match(cand):
                    run_ids.add(cand)
                break
    return sorted(run_ids)


def _iter_sidecars(runs_dir: Path, run_id: str) -> list[tuple[str, int, Path]]:
    out: list[tuple[str, int, Path]] = []
    for entry in runs_dir.iterdir():
        m = _ITER_SIDECAR_RE.match(entry.name)
        if m and m.group("run_id") == run_id:
            out.append((m.group("node_id"), int(m.group("iter")), entry))
    return out


def _rebuild_tool_calls_from_events(
    events_path: Path,
) -> dict[tuple[str, int], list[dict]]:
    """Scan events.json for tool_call + tool_result events, group by (node, iter).

    Returns a mapping (node_id, iter_num) → list of merged tool_call dicts.
    Each tool_call dict has {tool_name, tool_args, tool_result?} — result
    is filled if a matching tool_result event exists.
    """
    if not events_path.exists():
        return {}
    data = _load_json(events_path)
    if not isinstance(data, list):
        return {}

    by_key: dict[tuple[str, int], list[dict]] = defaultdict(list)
    pending_results: dict[tuple[str, int, str], dict] = {}

    for ev in data:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        payload = ev.get("payload") or {}
        node_id = payload.get("node_id")
        iter_num = payload.get("iteration") or payload.get("iter")
        if not isinstance(iter_num, int):
            iter_num = payload.get("iteration")
        if not node_id or not isinstance(iter_num, int):
            continue

        if etype == "agent.tool_call":
            entry = {
                "tool_name": payload.get("tool_name"),
                "tool_args": payload.get("tool_args") or payload.get("args") or {},
                "seq": ev.get("seq"),
                "ts": ev.get("ts"),
            }
            by_key[(node_id, iter_num)].append(entry)
            # Track for later result matching.
            pending_results[(node_id, iter_num, payload.get("tool_name") or "")] = entry

        elif etype == "agent.tool_result":
            key = (node_id, iter_num, payload.get("tool_name") or "")
            target = pending_results.get(key)
            if target is not None and "tool_result" not in target:
                target["tool_result"] = payload.get("tool_result") or payload.get("result")

    return dict(by_key)


def plan_run_migration(run_id: str, runs_dir: Path) -> MigrationPlan:
    """Inspect a run and produce a migration plan. No writes."""
    plan = MigrationPlan(run_id=run_id)

    # Snapshot check — v1 = no version field.
    snap_path = runs_dir / f"{run_id}+snapshot.json"
    if snap_path.exists():
        snap = _load_json(snap_path)
        if snap is None:
            plan.errors.append(f"unparseable snapshot {snap_path.name}")
        else:
            if isinstance(snap, dict):
                if snap.get("version") is None:
                    plan.snapshots_needing_v1_marker = True
                # Skip streaming snapshots (can't safely rebuild).
                if snap.get("status") == "running":
                    plan.skipped_streaming.append(
                        f"{snap_path.name} (status=running — may still be active)"
                    )

    # Sidecar checks — v1 = tool_calls field absent. Once the key exists
    # (even as an empty list), the sidecar is v2-shape and we don't touch
    # it on re-runs (idempotency).
    events_path = runs_dir / f"{run_id}+events.json"
    rebuilt = _rebuild_tool_calls_from_events(events_path) if events_path.exists() else {}

    for node_id, iter_num, path in _iter_sidecars(runs_dir, run_id):
        sidecar = _load_json(path)
        if sidecar is None:
            plan.errors.append(f"unparseable sidecar {path.name}")
            continue
        if "tool_calls" in sidecar:
            continue  # already v2-shape (idempotent)
        # Mark as needing rebuild.
        if (node_id, iter_num) in rebuilt:
            plan.sidecars_needing_tool_calls.append(
                f"{path.name} → would add {len(rebuilt[(node_id, iter_num)])} tool_calls"
            )
        else:
            # No events to rebuild from — note but don't fail.
            plan.sidecars_needing_tool_calls.append(
                f"{path.name} → no events.json data; would set tool_calls=[]"
            )

    return plan


def execute_migration(run_id: str, runs_dir: Path) -> MigrationPlan:
    """Apply the migration plan. Writes are atomic per-file."""
    plan = plan_run_migration(run_id, runs_dir)
    if not plan.has_work:
        return plan

    events_path = runs_dir / f"{run_id}+events.json"
    rebuilt = _rebuild_tool_calls_from_events(events_path) if events_path.exists() else {}

    # Sidecar tool_calls rebuild.
    for node_id, iter_num, path in _iter_sidecars(runs_dir, run_id):
        sidecar = _load_json(path)
        if sidecar is None:
            continue
        if "tool_calls" in sidecar:
            continue  # idempotent: don't touch v2-shape sidecars
        sidecar["tool_calls"] = rebuilt.get((node_id, iter_num), [])
        try:
            _save_atomic(path, sidecar)
            logger.info("migrated %s (tool_calls=%d)", path.name, len(sidecar["tool_calls"]))
        except OSError as exc:
            plan.errors.append(f"failed to write {path.name}: {exc}")

    # Snapshot v1 marker.
    if plan.snapshots_needing_v1_marker:
        snap_path = runs_dir / f"{run_id}+snapshot.json"
        snap = _load_json(snap_path)
        if snap is not None and isinstance(snap, dict):
            # Skip streaming snapshots.
            if snap.get("status") == "running":
                logger.warning("skip %s — status=running", snap_path.name)
            else:
                snap.setdefault("version", 1)
                snap.setdefault("migrated_at", int(time.time()))
                try:
                    _save_atomic(snap_path, snap)
                    logger.info("marked %s as v1 (migrated_at=%d)", snap_path.name, snap["migrated_at"])
                except OSError as exc:
                    plan.errors.append(f"failed to write {snap_path.name}: {exc}")

    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy v1 run records to v2 (rebuild sidecar tool_calls, "
                    "mark snapshots with version=1). Idempotent. Use --dry-run first.",
    )
    parser.add_argument(
        "--runs-dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "runs",
        help="runs/ directory (default: <project>/runs)",
    )
    parser.add_argument("--run-id", help="Migrate only this run_id (default: all)")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Plan only, write nothing (default: True).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes (cancels --dry-run).",
    )
    args = parser.parse_args(argv)

    if not args.runs_dir.exists():
        print(f"ERROR: runs dir {args.runs_dir} does not exist", file=sys.stderr)
        return 2

    run_ids = [args.run_id] if args.run_id else _list_runs(args.runs_dir)
    if not run_ids:
        print(f"No runs found in {args.runs_dir}")
        return 0

    dry_run = not args.apply
    print(f"{'DRY-RUN' if dry_run else 'APPLY'} — {len(run_ids)} run(s) in {args.runs_dir}\n")

    any_errors = False
    for rid in run_ids:
        if dry_run:
            plan = plan_run_migration(rid, args.runs_dir)
        else:
            plan = execute_migration(rid, args.runs_dir)

        print(f"=== {rid} ===")
        if plan.errors:
            any_errors = True
            for e in plan.errors:
                print(f"  ERROR: {e}")
        if not plan.has_work:
            print("  (nothing to migrate)")
        if plan.sidecars_needing_tool_calls:
            print(f"  sidecars needing tool_calls ({len(plan.sidecars_needing_tool_calls)}):")
            for s in plan.sidecars_needing_tool_calls[:5]:
                print(f"    - {s}")
            if len(plan.sidecars_needing_tool_calls) > 5:
                print(f"    ... +{len(plan.sidecars_needing_tool_calls) - 5} more")
        if plan.snapshots_needing_v1_marker:
            print("  snapshot: would mark version=1 + migrated_at")
        for skip in plan.skipped_streaming:
            print(f"  SKIP: {skip}")
        print()

    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
