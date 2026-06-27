#!/usr/bin/env python
"""check_resume.py — unified skip-if-exists + JSON validity checker.

Called at the top of each SETUP / cycle agent's Step 0 to decide whether
to skip execution because all required artifacts already exist from a
prior (interrupted) run.

Input:
  --session-dir <path>   NAS session directory (absolute)
  --expected <name>...   Filenames to check (relative to session_dir).

Output (stdout JSON):
  {
    "skip": true | false,
    "reason": "all files present and valid JSON" | "missing: [...]" | "invalid json: [...]",
    "files": [{"name": ..., "exists": bool, "valid_json": bool, "error": str | null}]
  }

Behavior:
  - For each expected file:
      * exists? → if not, mark missing
      * valid JSON? → if not (when file ends with .json), mark invalid
  - skip=true iff all files exist AND all .json files parse cleanly.

Schema validation (Pydantic) is intentionally NOT done here — helpers
stay framework-agnostic. Agent-level result_type validation handles schema
enforcement when the agent reads the file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_resume(session_dir: Path, expected: list[str]) -> dict:
    """Pure function — check whether all expected files exist + are valid JSON.

    Args:
        session_dir: Absolute path to NAS session dir.
        expected: List of filenames relative to session_dir.

    Returns:
        {skip, reason, files}
    """
    files_report = []
    missing: list[str] = []
    invalid: list[str] = []

    for name in expected:
        path = session_dir / name
        entry = {"name": name, "exists": False, "valid_json": False, "error": None}

        if not path.exists():
            entry["error"] = "not found"
            missing.append(name)
            files_report.append(entry)
            continue

        entry["exists"] = True

        # Only validate JSON for .json files (skip .md, .log, .patch, etc).
        if path.suffix == ".json":
            try:
                path.read_text()
                json.loads(path.read_text())
                entry["valid_json"] = True
            except (json.JSONDecodeError, OSError) as e:
                entry["error"] = f"invalid json: {e}"
                invalid.append(name)
        else:
            # Non-JSON file: existence is enough.
            entry["valid_json"] = True

        files_report.append(entry)

    if missing:
        reason = f"missing: {missing}"
        skip = False
    elif invalid:
        reason = f"invalid json: {invalid}"
        skip = False
    else:
        reason = f"all {len(expected)} files present and valid"
        skip = True

    return {"skip": skip, "reason": reason, "files": files_report}


def main() -> None:
    p = argparse.ArgumentParser(description="Skip-if-exists + JSON validity check")
    p.add_argument("--session-dir", required=True, help="Absolute session dir path")
    p.add_argument("--expected", required=True, nargs="+",
                   help="Filenames relative to session_dir (space-separated)")
    args = p.parse_args()

    session_dir = Path(args.session_dir)
    if not session_dir.exists():
        # Session dir itself missing → definitely not skippable.
        result = {
            "skip": False,
            "reason": f"session_dir does not exist: {session_dir}",
            "files": [],
        }
        print(json.dumps(result, indent=2))
        return

    result = check_resume(session_dir, args.expected)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
