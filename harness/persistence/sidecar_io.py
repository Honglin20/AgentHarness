"""sidecar_io — atomic, safe JSON write helpers for sidecar files.

This module centralizes all sidecar / snapshot write logic so that:
  1. Every write is atomic (tmpfile + os.replace) — file is never half-written.
  2. Every write is verified (read-back) — catches silent corruption from
     disk full / permission errors.
  3. Iter sidecar writes follow R3 (ADR §R3): retry once, log loud on
     persistent failure, do NOT raise — observation-layer loss must not
     block business logic.

ADR basis:
  - R3: sidecar write failure → retry + log + don't fail node
  - D7: sidecar is a lifecycle entity; atomic rename is the durability
        primitive that makes streaming → completed transitions safe.
  - I8: sidecar writes always go through atomic rename (this module).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TMP_SUFFIX = ".tmp"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_ITER_SIDECAR_PREFIX = "+iters+"
_ITER_SIDECAR_SUFFIX = ".json"


def atomic_write_json(path: Path, data: dict) -> None:
    """Write ``data`` as JSON to ``path`` atomically.

    Writes to ``path.tmp`` first, then ``os.replace`` to ``path``. POSIX
    guarantees ``os.replace`` is atomic, so readers see either the old
    file or the new file — never a partial write.

    Raises:
        FileNotFoundError: if the parent directory does not exist. We do
            NOT auto-mkdir here — sidecar paths are derived from run_id
            and the runs/ directory is created by RunStore at init.
        OSError: on any other I/O failure (disk full, permission, etc.).
    """
    content = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_suffix(path.suffix + _TMP_SUFFIX)
    try:
        tmp_path.write_text(content)
        os.replace(str(tmp_path), str(path))
    except BaseException:
        # Cleanup tmp on any failure (including CancelledError). Best-effort.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to clean up tmp file %s", tmp_path, exc_info=True)
        raise


def verify_write(path: Path, expected: dict) -> bool:
    """Read back ``path`` and compare to ``expected``.

    Returns True iff:
      - path exists and is non-empty,
      - contents parse as JSON,
      - parsed dict == expected (deep equality).

    Returns False on any I/O or parse error. Does NOT raise — callers
    decide how to react (retry, log, give up).
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        actual = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("verify_write failed for %s", path, exc_info=True)
        return False
    return actual == expected


def _resolve_runs_dir(runs_dir: Path | None) -> Path:
    """Return the effective runs dir, defaulting to harness.paths.get_runs_dir().

    Local import avoids a circular dependency at module import time and
    respects HARNESS_RUNS_DIR env override.
    """
    if runs_dir is not None:
        return runs_dir
    from harness.paths import get_runs_dir
    return get_runs_dir()


def save_iter_sidecar_safe(
    run_id: str,
    node_id: str,
    iter_num: int,
    data: dict,
    *,
    runs_dir: Path | None = None,
    max_retries: int = 1,
) -> bool:
    """Persist a per-iter sidecar with R3 safety guarantees.

    Sequence:
      1. Compute target path under ``runs_dir`` (or default runs/).
      2. ``atomic_write_json`` + ``verify_write``.
      3. On failure: retry up to ``max_retries`` times.
      4. Still failing: log WARNING with full context, return False.

    Returns:
        True on success, False on persistent failure. Never raises —
        business logic (node output_result) is independent of sidecar
        observation, and an exception here would crash the workflow.

    Args:
        run_id, node_id, iter_num: identity triple. Validated against
            ``[a-zA-Z0-9_-]+`` to prevent path traversal.
        data: dict payload (must JSON-serialize).
        runs_dir: optional override (defaults to harness.paths.get_runs_dir()).
        max_retries: extra attempts after the first failure (default 1).
    """
    # Validate identity triple — fail loud on bad input (programmer error,
    # not runtime I/O). This is BEFORE the don't-raise contract kicks in.
    if not _SAFE_ID_RE.match(run_id) or not _SAFE_ID_RE.match(node_id):
        raise ValueError(
            f"Invalid run_id or node_id (must match {_SAFE_ID_RE.pattern}): "
            f"run_id={run_id!r} node_id={node_id!r}"
        )
    if not isinstance(iter_num, int) or iter_num < 1:
        raise ValueError(f"iter_num must be a positive int, got {iter_num!r}")

    base = _resolve_runs_dir(runs_dir)
    path = base / f"{run_id}{_ITER_SIDECAR_PREFIX}{node_id}+{iter_num}{_ITER_SIDECAR_SUFFIX}"

    attempts = max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            atomic_write_json(path, data)
            if verify_write(path, data):
                if attempt > 1:
                    logger.info(
                        "sidecar write succeeded on retry %d: %s", attempt - 1, path
                    )
                return True
            logger.warning(
                "sidecar verify failed (attempt %d/%d) for %s",
                attempt, attempts, path,
            )
        except OSError as exc:
            last_exc = exc
            logger.warning(
                "sidecar write OSError (attempt %d/%d) for %s: %s",
                attempt, attempts, path, exc,
            )
        except Exception as exc:  # noqa: BLE001 — R3: never raise to caller
            last_exc = exc
            logger.warning(
                "sidecar write unexpected error (attempt %d/%d) for %s: %s",
                attempt, attempts, path, exc,
                exc_info=True,
            )

    logger.warning(
        "sidecar write permanently failed after %d attempts: run=%s node=%s iter=%d path=%s exc=%r",
        attempts, run_id, node_id, iter_num, path, last_exc,
    )
    return False

