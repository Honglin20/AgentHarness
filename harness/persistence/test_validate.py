"""Unit tests for harness/persistence/validate.py.

3 functions × 3 scenarios each = 9 cases:
  - OK case loads a real fixture file from tests/fixtures/.
  - Missing-required case verifies errors are reported with field name.
  - Additional-property case verifies unknown fields are rejected
    (additionalProperties: false).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.persistence.validate import (
    validate_iter_index,
    validate_iter_sidecar,
    validate_snapshot,
)

_FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# --- validate_snapshot ----------------------------------------------------

def test_validate_snapshot_ok():
    """Real fixture passes validation (no errors)."""
    assert validate_snapshot(_load("snapshot_ok.json")) == []


def test_validate_snapshot_missing_required():
    """Missing required field is reported with field name."""
    errors = validate_snapshot({})  # no run_id, workflow_name, status, dag
    msgs = " ".join(errors)
    for required in ("run_id", "workflow_name", "status", "dag"):
        assert required in msgs, f"expected '{required}' in errors: {errors}"


def test_validate_snapshot_rejects_unknown_field():
    """additionalProperties:false — unknown top-level field is rejected."""
    data = _load("snapshot_ok.json")
    data["__unexpected__"] = "boom"
    errors = validate_snapshot(data)
    assert any("__unexpected__" in e for e in errors), errors


# --- validate_iter_sidecar ------------------------------------------------

def test_validate_iter_sidecar_ok():
    """Real fixture passes validation (legacy fields tolerated)."""
    assert validate_iter_sidecar(_load("iter_sidecar_ok.json")) == []


def test_validate_iter_sidecar_missing_required():
    """Missing iter or node_id is reported."""
    errors = validate_iter_sidecar({"status": "completed"})
    msgs = " ".join(errors)
    assert "iter" in msgs and "node_id" in msgs, errors


def test_validate_iter_sidecar_rejects_bad_status():
    """status enum: unknown value rejected."""
    data = _load("iter_sidecar_ok.json")
    data["status"] = "frobnicated"
    errors = validate_iter_sidecar(data)
    assert any("status" in e and "frobnicated" in e for e in errors), errors


# --- validate_iter_index --------------------------------------------------

def test_validate_iter_index_ok():
    """Real fixture passes validation."""
    assert validate_iter_index(_load("iter_index_ok.json")) == []


def test_validate_iter_index_missing_required():
    """iter entry missing required iter/status/summary is reported."""
    bad = {"scout": [{"duration_ms": 100}]}  # missing iter, status, summary
    errors = validate_iter_index(bad)
    msgs = " ".join(errors)
    assert "iter" in msgs and "status" in msgs and "summary" in msgs, errors


def test_validate_iter_index_rejects_non_array_value():
    """Each node value must be an array (patternProperties $ref)."""
    bad = {"scout": "not-an-array"}
    errors = validate_iter_index(bad)
    assert errors, "expected validation error for non-array value"
    assert any("array" in e or "is not of type" in e for e in errors)
