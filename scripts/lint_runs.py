#!/usr/bin/env python3
"""lint_runs — CI / manual lint for runs/ directory.

Scans runs/ for invariant violations (ADR §不变量 I1-I9 + schema checks).
Outputs a human-readable report. Exit code: 0 OK, 1 if any violation found.

Schema checks (via harness.persistence.validate):
  - snapshot.v2.schema.json
  - iter_sidecar.v2.schema.json
  - iter_index.v2.schema.json

Invariant checks (ADR I1-I9 — see ADR.md):
  - I1: iter_index[N] count == count of {run}+iters+{N}+{i}.json files
  - I3: snapshot.nodes_latest[N].latest_iter == max(iter_index[N].iter)
  - I6: snapshot size < 50 KB
  - I7: sidecar has last_seq (P2b+; warn-only pre-P2b)
  - I8: no leftover .tmp files in runs/
  - I9: snapshot has no todo_states (P4+; warn-only pre-P4)

Usage:
  python scripts/lint_runs.py [--runs-dir runs] [--run-id <id>] [--strict]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Import harness modules — fail loud if missing.
try:
    from harness.paths import get_runs_dir as _default_runs_dir
    from harness.persistence.validate import (
        validate_iter_index,
        validate_iter_sidecar,
        validate_snapshot,
    )
except ImportError as exc:
    print(f"ERROR: cannot import harness modules: {exc}", file=sys.stderr)
    print("Run from the project root.", file=sys.stderr)
    sys.exit(2)


# Filename conventions (must mirror harness/persistence/run_store.py).
_ITER_INDEX_SUFFIX = "+iter_index.json"
_SNAPSHOT_SUFFIX = "+snapshot.json"
_OUTLINE_SUFFIX = "+outline.json"
_ITER_SIDECAR_PREFIX = "+iters+"
_ITER_SIDECAR_SUFFIX = ".json"
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_ITER_SIDECAR_RE = re.compile(
    r"^(?P<run_id>[a-zA-Z0-9_-]+)\+iters\+(?P<node_id>[a-zA-Z0-9_-]+)\+(?P<iter>\d+)\.json$"
)

# Size threshold per ADR I6. 50 KB is the "manifest" ceiling — anything
# bigger means we're back to embedding heavy data (regression).
_SNAPSHOT_MAX_BYTES = 50 * 1024


@dataclass
class RunReport:
    """All violations + warnings for a single run_id."""

    run_id: str
    schema_errors: dict[str, list[str]] = field(default_factory=dict)  # file → errors
    invariant_errors: list[str] = field(default_factory=list)
    invariant_warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.schema_errors or self.invariant_errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.invariant_warnings)


def _list_runs(runs_dir: Path) -> list[str]:
    """Return sorted list of distinct run_ids in runs_dir."""
    run_ids: set[str] = set()
    for entry in runs_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        # Strip known suffixes to recover run_id
        for suffix in (
            _ITER_INDEX_SUFFIX, _SNAPSHOT_SUFFIX, _OUTLINE_SUFFIX,
            "+charts.json", "+events.json", ".json",  # main record
        ):
            if name.endswith(suffix):
                candidate = name[: -len(suffix)]
                if _RUN_ID_RE.match(candidate):
                    run_ids.add(candidate)
                break
        else:
            m = _ITER_SIDECAR_RE.match(name)
            if m:
                run_ids.add(m.group("run_id"))
    return sorted(run_ids)


def _load_json(path: Path) -> dict | None:
    """Load JSON or None on parse error (errors printed by caller)."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _iter_sidecars_for(runs_dir: Path, run_id: str) -> list[tuple[str, int, Path]]:
    """List (node_id, iter_num, path) for all iter sidecars of run_id."""
    out: list[tuple[str, int, Path]] = []
    for entry in runs_dir.iterdir():
        if not entry.is_file():
            continue
        m = _ITER_SIDECAR_RE.match(entry.name)
        if m and m.group("run_id") == run_id:
            out.append((m.group("node_id"), int(m.group("iter")), entry))
    return out


# === Schema checks (delegated to harness.persistence.validate) ===

def check_schemas(run_id: str, runs_dir: Path, report: RunReport) -> None:
    """Validate every sidecar/snapshot/index file for this run against v2 schemas."""
    # Snapshot
    snap_path = runs_dir / f"{run_id}{_SNAPSHOT_SUFFIX}"
    if snap_path.exists():
        data = _load_json(snap_path)
        if data is None:
            report.schema_errors[str(snap_path)] = ["<unparseable JSON>"]
        else:
            errs = validate_snapshot(data)
            if errs:
                report.schema_errors[str(snap_path)] = errs

    # iter_index
    idx_path = runs_dir / f"{run_id}{_ITER_INDEX_SUFFIX}"
    if idx_path.exists():
        data = _load_json(idx_path)
        if data is None:
            report.schema_errors[str(idx_path)] = ["<unparseable JSON>"]
        else:
            errs = validate_iter_index(data)
            if errs:
                report.schema_errors[str(idx_path)] = errs

    # Each iter sidecar
    for node_id, _iter, path in _iter_sidecars_for(runs_dir, run_id):
        data = _load_json(path)
        if data is None:
            report.schema_errors[str(path)] = ["<unparseable JSON>"]
            continue
        errs = validate_iter_sidecar(data)
        if errs:
            report.schema_errors[str(path)] = errs


# === Invariant checks (ADR I1-I9) ===

def check_i1_iter_index_matches_files(
    run_id: str, runs_dir: Path, iter_index: dict | None
) -> list[str]:
    """I1: iter_index[N] iters match files on disk."""
    if iter_index is None:
        return []
    sidecars_by_node: dict[str, set[int]] = defaultdict(set)
    for node_id, iter_num, _ in _iter_sidecars_for(runs_dir, run_id):
        sidecars_by_node[node_id].add(iter_num)

    violations: list[str] = []
    # Every sidecar file must appear in iter_index
    for node_id, files_iters in sidecars_by_node.items():
        index_entries = iter_index.get(node_id) or []
        index_iters = {
            e.get("iter") for e in index_entries
            if isinstance(e, dict) and isinstance(e.get("iter"), int)
        }
        missing_from_index = files_iters - index_iters
        if missing_from_index:
            violations.append(
                f"I1: {node_id} sidecars on disk for iters {sorted(missing_from_index)} "
                f"but iter_index has only {sorted(index_iters)}"
            )
    # Every iter_index entry must have a matching sidecar file
    for node_id, entries in iter_index.items():
        index_iters = {
            e.get("iter") for e in entries
            if isinstance(e, dict) and isinstance(e.get("iter"), int)
        }
        on_disk = sidecars_by_node.get(node_id, set())
        missing_files = index_iters - on_disk
        if missing_files:
            violations.append(
                f"I1: {node_id} iter_index claims iters {sorted(missing_files)} "
                f"but no sidecar files exist (disk iters: {sorted(on_disk)})"
            )
    return violations


def check_i3_latest_iter_consistency(
    snapshot: dict | None, iter_index: dict | None
) -> list[str]:
    """I3: snapshot.nodes_latest[N].latest_iter == max(iter_index[N].iter)."""
    if snapshot is None or iter_index is None:
        return []
    nodes_latest = snapshot.get("nodes_latest") or {}
    if not isinstance(nodes_latest, dict):
        return []
    violations: list[str] = []
    for node_id, meta in nodes_latest.items():
        if not isinstance(meta, dict):
            continue
        snap_iter = meta.get("latest_iter")
        if not isinstance(snap_iter, int):
            continue
        entries = iter_index.get(node_id) or []
        index_iters = [
            e.get("iter") for e in entries
            if isinstance(e, dict) and isinstance(e.get("iter"), int)
        ]
        if not index_iters:
            continue
        max_index = max(index_iters)
        if snap_iter != max_index:
            violations.append(
                f"I3: nodes_latest[{node_id}].latest_iter={snap_iter} but "
                f"iter_index max iter={max_index}"
            )
    return violations


def check_i6_snapshot_size(run_id: str, runs_dir: Path) -> list[str]:
    """I6: snapshot file size < 50 KB.

    Post-P4 this is enforced as ERROR — snapshots are manifests (ADR D3),
    carrying no conversation/agent_io/todo_states. Pre-P4 runs (legacy
    on-disk files written before the P4 migration) still embed heavy fields
    and would exceed the cap; those are reported as warnings to track the
    baseline without blocking CI.

    Detection: peek at the snapshot's ``version`` field. v2 snapshots are
    post-P4 manifests and must be under cap. v1 (no version field, or
    version < 2) is legacy and only warned.
    """
    snap_path = runs_dir / f"{run_id}{_SNAPSHOT_SUFFIX}"
    if not snap_path.exists():
        return []
    size = snap_path.stat().st_size
    if size <= _SNAPSHOT_MAX_BYTES:
        return []

    # Distinguish v2 (post-P4, must comply) from v1 (legacy, warn only).
    is_v2 = False
    try:
        data = json.loads(snap_path.read_text())
        is_v2 = isinstance(data, dict) and data.get("version") == 2
    except (OSError, json.JSONDecodeError):
        pass

    label = "v2 manifest" if is_v2 else "v1 legacy snapshot"
    severity = "ERROR" if is_v2 else "WARN (legacy baseline; P4 enforce)"
    return [
        f"I6 [{severity}]: snapshot {snap_path.name} is {size} bytes "
        f"(>{_SNAPSHOT_MAX_BYTES} = 50KB) — {label} should not embed heavy data"
    ]


def check_i7_sidecar_has_last_seq(run_id: str, runs_dir: Path) -> tuple[list[str], list[str]]:
    """I7: sidecars carry last_seq (P2b+ — warn pre-P2b).

    Returns (errors, warnings). Pre-P2b runs have no last_seq, so this is
    warn-only until P2b lands. After P2b, --strict promotes to error.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for node_id, _iter, path in _iter_sidecars_for(runs_dir, run_id):
        data = _load_json(path)
        if data is None:
            continue
        if "last_seq" not in data:
            warnings.append(
                f"I7: {path.name} missing last_seq (P2b will add this; "
                f"pre-P2b legacy sidecar)"
            )
    return errors, warnings


def check_i8_no_partial_files(run_id: str, runs_dir: Path) -> list[str]:
    """I8: no leftover .tmp files in runs/."""
    violations: list[str] = []
    for entry in runs_dir.iterdir():
        if entry.is_file() and entry.name.startswith(run_id) and entry.name.endswith(".tmp"):
            violations.append(
                f"I8: leftover tmp file {entry.name} — atomic write did not clean up"
            )
    return violations


def check_i9_no_todo_in_snapshot(snapshot: dict | None) -> tuple[list[str], list[str]]:
    """I9: snapshot has no todo_states (P4+ — warn pre-P4)."""
    if snapshot is None:
        return [], []
    if "todo_states" in snapshot and snapshot["todo_states"]:
        return [], [
            "I9: snapshot has non-empty todo_states (P4 will move this to sidecar)"
        ]
    return [], []


def lint_run(
    run_id: str, runs_dir: Path, strict: bool = False
) -> RunReport:
    """Run all schema + invariant checks for a single run_id."""
    report = RunReport(run_id=run_id)

    # Schema layer
    check_schemas(run_id, runs_dir, report)

    # Load index + snapshot for invariants (may be absent on partial runs)
    idx_path = runs_dir / f"{run_id}{_ITER_INDEX_SUFFIX}"
    iter_index = _load_json(idx_path) if idx_path.exists() else None

    snap_path = runs_dir / f"{run_id}{_SNAPSHOT_SUFFIX}"
    snapshot = _load_json(snap_path) if snap_path.exists() else None

    # I1
    report.invariant_errors.extend(
        check_i1_iter_index_matches_files(run_id, runs_dir, iter_index)
    )
    # I3
    report.invariant_errors.extend(
        check_i3_latest_iter_consistency(snapshot, iter_index)
    )
    # I6 (post-P4: v2 snapshot error; v1 legacy warn)
    i6_violations = check_i6_snapshot_size(run_id, runs_dir)
    for violation in i6_violations:
        if "ERROR" in violation:
            report.invariant_errors.append(violation)
        else:
            if strict:
                report.invariant_errors.append(violation)
            else:
                report.invariant_warnings.append(violation)
    # I7
    i7_errors, i7_warnings = check_i7_sidecar_has_last_seq(run_id, runs_dir)
    if strict:
        report.invariant_errors.extend(i7_errors)
        report.invariant_errors.extend(i7_warnings)  # in strict mode, warnings → errors
    else:
        report.invariant_warnings.extend(i7_warnings)
    # I8
    report.invariant_errors.extend(check_i8_no_partial_files(run_id, runs_dir))
    # I9
    i9_errors, i9_warnings = check_i9_no_todo_in_snapshot(snapshot)
    if strict:
        report.invariant_errors.extend(i9_warnings)
    else:
        report.invariant_warnings.extend(i9_warnings)

    return report


def format_report(report: RunReport) -> str:
    """Render a single run's report as a human-readable block."""
    lines: list[str] = [f"=== {report.run_id} ==="]
    if not report.has_errors and not report.has_warnings:
        lines.append("  OK")
        return "\n".join(lines)

    for path, errs in report.schema_errors.items():
        lines.append(f"  SCHEMA FAIL: {path}")
        for e in errs[:5]:
            lines.append(f"    - {e}")
        if len(errs) > 5:
            lines.append(f"    ... and {len(errs) - 5} more")

    for e in report.invariant_errors:
        lines.append(f"  ERROR: {e}")

    for w in report.invariant_warnings:
        lines.append(f"  WARN:  {w}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint runs/ directory for schema + ADR I1-I9 invariant violations.",
    )
    parser.add_argument(
        "--runs-dir", type=Path, default=None,
        help="Directory containing run files (default: harness.paths.get_runs_dir()).",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="Lint only this run_id. Default: lint all.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Promote warn-only invariants (I7 last_seq, I9 todo_states) to errors. "
             "Use in post-P2b/P4 CI to enforce the new contract.",
    )
    args = parser.parse_args(argv)

    runs_dir = args.runs_dir or _default_runs_dir()
    if not runs_dir.exists():
        print(f"ERROR: runs dir does not exist: {runs_dir}", file=sys.stderr)
        return 2

    if args.run_id:
        run_ids = [args.run_id]
    else:
        run_ids = _list_runs(runs_dir)

    if not run_ids:
        print(f"No runs found in {runs_dir}")
        return 0

    print(f"Scanning {len(run_ids)} run(s) in {runs_dir}\n")

    any_error = False
    total_errors = 0
    total_warnings = 0
    for rid in run_ids:
        report = lint_run(rid, runs_dir, strict=args.strict)
        print(format_report(report))
        if report.has_errors:
            any_error = True
            total_errors += (
                sum(len(v) for v in report.schema_errors.values())
                + len(report.invariant_errors)
            )
        total_warnings += len(report.invariant_warnings)

    print()
    print(f"Summary: {total_errors} error(s), {total_warnings} warning(s)")
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
