"""Builtin CLI profile registry + project-level profile loader (P3-T3 / P3-T8).

Startup contract:

  1. ``load_builtin_profiles()`` scans ``harness/cli_profiles/*.py`` (this
     package) and registers every module that exports a ``PROFILE``
     CliProfile. Idempotent — last-write-wins on name conflicts.

  2. ``load_project_profiles(cwd)`` scans ``<cwd>/.harness/cli_profiles/*.py``
     for project-level overrides. Same module-level ``PROFILE`` contract.
     Project profiles override builtins (last-write-wins).

  3. ``HARNESS_DISABLE_PROJECT_PROFILES=1`` skips step 2 (CI / shared
     directory scenarios where project-level profiles are undesirable).

  4. ``HARNESS_CLI_PROFILES_DIR=<path>`` overrides the project-level
     directory location (operator canary support).

Loader semantics (P3-T9 graceful degradation):

  - Broken module (syntax error / import error / missing PROFILE): log
    warning + call disable_profile(name, reason). The profile name
    remains in the registry (so VALID_EXECUTORS warns operators about
    the broken profile rather than silently dropping it). Using the
    disabled profile raises ValueError at get_profile time.
  - Server / CLI startup NEVER blocks on a broken profile.

Persistence contract (ADR Decision 3, mirrors harness/config.py:15-20):

  Operators edit ``./.harness/cli_profiles/<name>.py`` and restart the
  server / CLI — the new profile is auto-discovered, no core code changes
  required.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path

from harness.engine.cli_profile import (
    CliProfile,
    disable_profile,
    register_cli_profile,
)

logger = logging.getLogger(__name__)


#: Environment variable to disable project-level profile loading entirely
#: (CI / shared directory scenarios).
DISABLE_PROJECT_PROFILES_ENV = "HARNESS_DISABLE_PROJECT_PROFILES"

#: Environment variable to override the project-level profiles directory.
PROJECT_PROFILES_DIR_ENV = "HARNESS_CLI_PROFILES_DIR"

#: Default project-level profiles directory (relative to CWD).
DEFAULT_PROJECT_PROFILES_DIRNAME = ".harness/cli_profiles"

#: Required module-level attribute a profile module must export.
PROFILE_ATTR = "PROFILE"


# ---------------------------------------------------------------------------
# Module loading primitives
# ---------------------------------------------------------------------------


def _load_profile_from_path(path: Path) -> CliProfile | None:
    """Load a single profile module from ``path`` and return its PROFILE.

    Returns None on any error — caller decides what to do with the
    diagnostic (caller knows the profile name to disable).

    Errors handled here:
      - syntax / import errors
      - missing PROFILE attribute
      - PROFILE is not a CliProfile instance
    """
    module_name = f"_harness_cli_profile_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        logger.warning("could not build spec for %s", path)
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning(
            "profile module %s failed to import: %s: %s",
            path, type(exc).__name__, exc,
        )
        return None
    profile = getattr(module, PROFILE_ATTR, None)
    if profile is None:
        logger.warning(
            "profile module %s does not export %r — skipping",
            path, PROFILE_ATTR,
        )
        return None
    if not isinstance(profile, CliProfile):
        logger.warning(
            "profile module %s exported %r but it is %s, not CliProfile",
            path, PROFILE_ATTR, type(profile).__name__,
        )
        return None
    return profile


def _discover_profile_files(directory: Path) -> list[Path]:
    """Return sorted list of ``*.py`` files in directory (non-recursive).

    Sorted so registration order is deterministic across runs / platforms.
    Excludes ``__init__.py`` and other dunder files.
    """
    if not directory.is_dir():
        return []
    files = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix != ".py":
            continue
        if entry.name.startswith("_"):
            continue
        files.append(entry)
    return files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_builtin_profiles() -> int:
    """Scan ``harness/cli_profiles/`` for builtin profile modules.

    Returns the count of successfully-registered profiles. Idempotent.

    Builtin directory is determined from this package's __file__ so
    operators installing harness via pip / uv auto-pick up new builtins
    on upgrade.
    """
    builtin_dir = Path(__file__).resolve().parent
    return _load_directory(builtin_dir, label="builtin")


def load_project_profiles(cwd: Path | None = None) -> int:
    """Scan ``<cwd>/.harness/cli_profiles/`` for project-level overrides.

    Returns the count of successfully-registered profiles. Skipped (returns
    0) when ``HARNESS_DISABLE_PROJECT_PROFILES=1`` is set.

    Args:
        cwd: project root to scan from. Defaults to Path.cwd().
    """
    if os.environ.get(DISABLE_PROJECT_PROFILES_ENV):
        logger.info(
            "project-level profiles disabled via %s",
            DISABLE_PROJECT_PROFILES_ENV,
        )
        return 0

    cwd_path = Path(cwd) if cwd else Path.cwd()
    override = os.environ.get(PROJECT_PROFILES_DIR_ENV)
    if override:
        project_dir = Path(override)
    else:
        project_dir = cwd_path / DEFAULT_PROJECT_PROFILES_DIRNAME
    return _load_directory(project_dir, label="project")


def _load_directory(directory: Path, label: str) -> int:
    """Load every profile file in directory. Returns count registered.

    Per-file errors are isolated — one broken profile does not block
    the others. Each broken profile gets disable_profile() called so
    operators see the failure in disabled_profile_diagnostics().
    """
    files = _discover_profile_files(directory)
    if not files:
        logger.debug("no profile files in %s directory: %s", label, directory)
        return 0
    registered = 0
    for path in files:
        # Profile name default = filename stem. If the loaded PROFILE
        # has a different .name attribute, that wins (caller intent).
        default_name = path.stem
        profile = _load_profile_from_path(path)
        if profile is None:
            # Module failed to load or didn't export a valid PROFILE.
            # Disable by filename stem so users get a clear error if
            # they try to use it.
            disable_profile(
                default_name,
                f"module {path.name} failed to load (see startup log)",
            )
            continue
        try:
            register_cli_profile(profile)
            registered += 1
            logger.info(
                "registered %s profile %s from %s",
                label, profile.name, path,
            )
        except Exception as exc:
            disable_profile(
                profile.name,
                f"register_cli_profile raised {type(exc).__name__}: {exc}",
            )
            logger.warning(
                "failed to register %s profile %s from %s: %s",
                label, profile.name, path, exc,
            )
    return registered


def load_all_profiles_at_startup(cwd: Path | None = None) -> tuple[int, int]:
    """Convenience: load builtin then project profiles.

    Returns (builtin_count, project_count). Used by harness/cli.py and
    server/main.py entry points.
    """
    builtin_count = load_builtin_profiles()
    project_count = load_project_profiles(cwd)
    return builtin_count, project_count


# ---------------------------------------------------------------------------
# Eager builtin registration on import (so simple `import harness.cli_profiles`
# is sufficient for tests / REPL use). Server / CLI entry points also call
# load_all_profiles_at_startup explicitly to also pick up project-level.
# ---------------------------------------------------------------------------

# Guard against double-load on module reload (tests use reset_registry)
if not getattr(sys.modules.get(__name__), "_BUILTINS_LOADED", False):
    try:
        load_builtin_profiles()
    except Exception:  # pragma: no cover — defensive
        logger.exception("builtin profile load failed at import time")
    _BUILTINS_LOADED = True
