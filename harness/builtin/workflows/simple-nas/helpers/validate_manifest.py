#!/usr/bin/env python
"""validate_manifest.py — Layer 2 of change-quota contract.

Coder sub_agent must invoke this after writing manifest.json. exit 0 =
strategy is contract-compliant; exit 1 + stderr = drop the strategy
(planner collects exit-1 results and discards them from K).

Schema (Layer 1, devkit/nas/schemas.py:StrategyInfo) enforces type +
count at framework level; this helper re-checks with file-existence
verification for new_model_path that the schema cannot express.

Usage:
    python validate_manifest.py <manifest.json>
    python validate_manifest.py <manifest.json> --worktree <dir>
    python validate_manifest.py <manifest.json> --max-change-count 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VALID_TYPES = ("parametric", "structural_local", "structural_global")
DEFAULT_MAX_CHANGE_COUNT = 3  # MUST match devkit/nas/schemas.py:MAX_CHANGE_COUNT


def main() -> None:
    p = argparse.ArgumentParser(description="Validate manifest.json change-quota contract")
    p.add_argument("manifest", help="path to manifest.json")
    p.add_argument("--worktree", default=None,
                   help="worktree root for new_model_path existence check (relative paths resolved against this)")
    p.add_argument("--max-change-count", type=int, default=DEFAULT_MAX_CHANGE_COUNT,
                   help=f"upper bound for parametric/local change_count (default {DEFAULT_MAX_CHANGE_COUNT}, "
                        f"must match schemas.py:MAX_CHANGE_COUNT)")
    args = p.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {manifest_path}: {e}", file=sys.stderr)
        sys.exit(2)

    errors = _validate(manifest, args.max_change_count, args.worktree)
    if errors:
        for e in errors:
            print(f"VIOLATION: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({
        "status": "ok",
        "strategy_id": manifest.get("strategy_id"),
        "hypothesis_type": manifest.get("hypothesis_type"),
        "change_count": manifest.get("change_count"),
    }))


def _validate(manifest: dict, max_change_count: int, worktree: str | None) -> list[str]:
    """Return list of violation messages (empty = pass)."""
    errors: list[str] = []

    htype = manifest.get("hypothesis_type", "")
    if htype not in VALID_TYPES:
        errors.append(
            f"hypothesis_type must be one of {VALID_TYPES}, got {htype!r}"
        )
        # Cannot continue type-specific checks; bail early.
        return errors

    change_count = manifest.get("change_count")
    if not isinstance(change_count, int) or change_count < 1:
        errors.append(
            f"change_count must be positive int, got {change_count!r}"
        )
        return errors

    new_model_path = manifest.get("new_model_path")
    new_model_class = manifest.get("new_model_class")

    # Type-specific change_count bounds.
    if htype == "structural_global":
        if change_count != 1:
            errors.append(
                f"structural_global requires change_count=1 (single new model), got {change_count}"
            )
        if not new_model_path:
            errors.append("structural_global requires new_model_path (relative path within worktree)")
        if not new_model_class:
            errors.append("structural_global requires new_model_class (class name to import)")
    else:
        if change_count > max_change_count:
            errors.append(
                f"{htype} requires change_count <= {max_change_count}, got {change_count}"
            )
        if new_model_path is not None or new_model_class is not None:
            errors.append(
                f"{htype} must not set new_model_path/new_model_class "
                f"(reserved for structural_global)"
            )

    # ops_modified / files_changed consistency.
    ops_modified = manifest.get("ops_modified", [])
    if isinstance(ops_modified, list) and len(ops_modified) != change_count:
        errors.append(
            f"ops_modified.length ({len(ops_modified)}) must equal change_count ({change_count})"
        )

    files_changed = manifest.get("files_changed", [])
    if isinstance(files_changed, list) and len(files_changed) > max_change_count:
        errors.append(
            f"files_changed.length ({len(files_changed)}) exceeds max_change_count ({max_change_count})"
        )

    # new_model_path existence check (only if worktree provided).
    if htype == "structural_global" and new_model_path and worktree:
        candidate = Path(worktree) / new_model_path
        if not candidate.exists():
            errors.append(
                f"structural_global new_model_path does not exist: {candidate} "
                f"(worktree={worktree}, relative={new_model_path})"
            )

    return errors


if __name__ == "__main__":
    main()
