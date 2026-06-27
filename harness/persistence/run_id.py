"""Human-readable run_id generation.

Format: ``<workflow_slug>-YYYYMMDD-HHMM-<6hex>``
Example: ``nas-20260627-0949-a3f1b2``

The slug embeds workflow + timestamp so files in ``runs/`` are self-describing
and sortable. The 6-hex suffix (CSPRNG) provides ~16M possibilities per minute
per slug — matching the entropy-based uniqueness of the prior UUID4 approach,
so no ``run_exists`` collision check is needed at generation time.

Output matches ``_SAFE_ID_RE`` (``^[a-zA-Z0-9_-]+$``) enforced by
``harness.persistence.run_store`` and ``scripts.lint_runs``.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime

_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")
_MAX_SLUG_LEN = 30
_FALLBACK_SLUG = "run"


def _slugify(workflow_name: str) -> str:
    """workflow_name → filesystem-safe lowercase slug.

    Non-alphanumeric runs collapse to a single ``-``; result is trimmed,
    lowercased, and capped at ``_MAX_SLUG_LEN`` chars. Returns the
    ``run`` fallback when the input is empty, whitespace-only, or contains
    no alphanumerics (e.g. ``"!!!"``).
    """
    if not workflow_name:
        return _FALLBACK_SLUG
    slug = _NON_ALNUM_RE.sub("-", workflow_name).strip("-").lower()
    if not slug:
        return _FALLBACK_SLUG
    truncated = slug[:_MAX_SLUG_LEN].rstrip("-")
    return truncated or _FALLBACK_SLUG


def generate_run_id(workflow_name: str, *, now: datetime | None = None) -> str:
    """Return ``<slug>-YYYYMMDD-HHMM-<6hex>`` for the given workflow.

    ``now`` is injectable for deterministic tests.
    """
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    suffix = secrets.token_hex(3)  # 6 hex chars, CSPRNG
    return f"{_slugify(workflow_name)}-{ts}-{suffix}"
