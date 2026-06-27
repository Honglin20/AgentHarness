"""validate — schema-based validation for snapshot / iter_sidecar / iter_index.

Returns a list of human-readable error strings. Empty list = valid.

The functions collect ALL errors (not fail-fast) so a CI lint pass can
report every violation in one shot, instead of forcing N iterations to
uncover a chain of issues.

ADR basis:
  - I1-I9: invariant checks (this module is the schema layer; structural
    cross-file invariants live in scripts/lint_runs.py).
  - D2 / D3 / D7: schema definitions in schemas/*.v2.schema.json.
  - v3: iter_sidecar.v3.schema.json adds thinking / tool_streaming_outputs /
    schema_version / error fields (ADR: single-source-streaming-state D1).
    Default for iter_sidecar; v2 retained for legacy read compat.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "jsonschema is required for harness.persistence.validate. "
        "Install with: pip install jsonschema"
    ) from _exc


_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"

# Default schema versions per schema family. iter_sidecar defaults to v3
# (ADR: single-source-streaming-state); others remain on v2.
_DEFAULT_VERSIONS: dict[str, int] = {
    "iter_sidecar": 3,
    "snapshot": 2,
    "iter_index": 2,
}


@lru_cache(maxsize=16)
def _load_schema(name: str, version: int | None = None) -> dict:
    """Load a schema by short name (e.g. 'snapshot', 'iter_sidecar').

    Cached because schemas are read frequently from hot paths (lint, write
    pre-checks). Raises FileNotFoundError if schema file is missing —
    fail loud, never silently return an empty schema.

    When ``version`` is None, falls back to ``_DEFAULT_VERSIONS[name]``.
    Older versions are also kept readable — call ``_load_schema("iter_sidecar", 2)``
    to validate a legacy sidecar against the v2 schema.
    """
    if version is None:
        version = _DEFAULT_VERSIONS.get(name, 2)
    path = _SCHEMA_DIR / f"{name}.v{version}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    return json.loads(path.read_text())


def _iter_errors(schema_name: str, data: dict, version: int | None = None) -> list[str]:
    """Run Draft7Validator.iter_errors and format each as 'msg at /path/...'.

    Returns an empty list if data is valid.
    """
    schema = _load_schema(schema_name, version)
    validator = Draft7Validator(schema)
    errors: list[str] = []
    for err in validator.iter_errors(data):
        # Render the JSON path: ["agent_io", 0, "tool_calls"] → /agent_io/0/tool_calls
        path_str = "/" + "/".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
        errors.append(f"{err.message} at {path_str}")
    return errors


def validate_snapshot(data: dict) -> list[str]:
    """Validate a snapshot dict against snapshot.v2.schema.json.

    Returns list of error strings (empty if valid).
    """
    return _iter_errors("snapshot", data)


def validate_iter_sidecar(data: dict, version: int | None = None) -> list[str]:
    """Validate an iter sidecar dict.

    Defaults to v3 (ADR: single-source-streaming-state D1). Pass ``version=2``
    to validate legacy sidecars against the older schema. v3 is a superset —
    v2 sidecars still validate under v3 (new fields are optional).
    """
    return _iter_errors("iter_sidecar", data, version)


def validate_iter_index(data: dict) -> list[str]:
    """Validate an iter index dict against iter_index.v2.schema.json."""
    return _iter_errors("iter_index", data)

