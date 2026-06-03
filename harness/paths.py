"""Centralized project-root path resolution.

Priority chain:
  1. HARNESS_PROJECT_ROOT env var  (explicit override — used by CLI, CI, etc.)
  2. CWD heuristic                (workflows/ or harness/ exists in cwd)
  3. Package parent fallback      (Path(__file__).parent.parent — works in dev & pip-install)

User-facing data (runs, checkpoints) always prefers CWD so it stays in the
user's project directory, regardless of where the harness package lives.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "get_project_root",
    "get_workflows_dir",
    "get_benchmarks_dir",
    "get_runs_dir",
    "get_shared_agents_dir",
    "get_shared_scripts_dir",
    "get_env_file",
    "get_checkpoint_db_path",
    "get_profiles_file",
]

# Module-level constant — stable across calls within the same process.
_PACKAGE_DIR = Path(__file__).resolve().parent


def get_project_root() -> Path:
    """Return the project root directory.

    Resolution order:
      1. HARNESS_PROJECT_ROOT environment variable (if set and non-empty)
      2. CWD heuristic — if CWD contains ``workflows/`` or ``harness/``
      3. Fallback — parent of the ``harness`` package directory

    Intentionally re-evaluated on each call (not cached) so that test
    monkeypatches (setenv / chdir) take effect immediately.  Module-level
    consumers (e.g. ``harness.api._WORKFLOWS_DIR``) capture the result once
    at import time, which is the desired behaviour for production use.
    """
    # 1. Explicit env var
    env_root = os.environ.get("HARNESS_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()

    # 2. CWD heuristic
    cwd = Path.cwd()
    if (cwd / "workflows").is_dir() or (cwd / "harness").is_dir():
        return cwd.resolve()

    # 3. Package parent fallback
    return _PACKAGE_DIR.parent


# ── derived paths ──────────────────────────────────────────────────


def get_workflows_dir() -> Path:
    return get_project_root() / "workflows"


def get_benchmarks_dir() -> Path:
    return get_project_root() / "benchmarks"


def get_runs_dir() -> Path:
    """Runs directory — prefers CWD so user data stays in their project.

    Priority:
      1. HARNESS_RUNS_DIR env var  (explicit override)
      2. CWD/runs/                 (user's current working directory)
    """
    env_dir = os.environ.get("HARNESS_RUNS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    return Path.cwd().resolve() / "runs"


def get_shared_agents_dir() -> Path:
    return get_project_root() / "workflows" / "_shared" / "agents"


def get_shared_scripts_dir() -> Path:
    return get_project_root() / "workflows" / "_shared" / "scripts"


def get_env_file() -> Path:
    return get_project_root() / ".env"


def get_checkpoint_db_path() -> Path:
    return get_runs_dir() / "checkpoints.db"


def get_profiles_file() -> Path:
    """Return path to profiles.json — co-located with .env."""
    cwd = Path.cwd()
    if (cwd / ".env").exists():
        return cwd / "profiles.json"
    return get_project_root() / "profiles.json"
