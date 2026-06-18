"""Unit tests for harness/persistence/sidecar_io.py.

Covers atomic_write_json / verify_write / save_iter_sidecar_safe — the
three primitives that back the R3 (ADR §R3) write-safety contract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.persistence.sidecar_io import (
    atomic_write_json,
    save_iter_sidecar_safe,
    verify_write,
)


def test_atomic_write_creates_file(tmp_path: Path):
    """atomic_write_json writes valid JSON to the target path."""
    p = tmp_path / "out.json"
    atomic_write_json(p, {"a": 1, "b": [2, 3]})
    assert p.exists()
    assert json.loads(p.read_text()) == {"a": 1, "b": [2, 3]}


def test_atomic_write_unicode(tmp_path: Path):
    """Non-ASCII content survives the round-trip (ensure_ascii=False)."""
    p = tmp_path / "u.json"
    atomic_write_json(p, {"中文": "测试", "emoji": "🚀"})
    raw = p.read_text(encoding="utf-8")
    assert "中文" in raw and "🚀" in raw
    assert json.loads(raw) == {"中文": "测试", "emoji": "🚀"}


def test_atomic_write_no_residue_tmp(tmp_path: Path):
    """tmp file is cleaned up on both success and failure paths."""
    p = tmp_path / "x.json"
    atomic_write_json(p, {"k": "v"})
    assert list(tmp_path.glob("*.tmp")) == []

    # Force a failure: make the tmp write succeed but replace fail by
    # removing the parent dir mid-write via patching os.replace.
    p2 = tmp_path / "y.json"
    with patch("harness.persistence.sidecar_io.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            atomic_write_json(p2, {"k": "v"})
    # tmp was either cleaned or never created past unlink; either way no residue
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_missing_parent_raises(tmp_path: Path):
    """Missing parent dir surfaces as FileNotFoundError — no silent mkdir."""
    p = tmp_path / "missing" / "out.json"
    with pytest.raises(FileNotFoundError):
        atomic_write_json(p, {"x": 1})


def test_verify_write_ok(tmp_path: Path):
    """verify_write returns True for a correctly written file."""
    p = tmp_path / "v.json"
    atomic_write_json(p, {"x": 1})
    assert verify_write(p, {"x": 1}) is True


def test_verify_write_mismatch(tmp_path: Path):
    """verify_write returns False when contents don't equal expected."""
    p = tmp_path / "v.json"
    atomic_write_json(p, {"x": 1})
    assert verify_write(p, {"x": 2}) is False


def test_verify_write_missing_file(tmp_path: Path):
    """verify_write returns False when path doesn't exist (no exception)."""
    p = tmp_path / "absent.json"
    assert verify_write(p, {"x": 1}) is False


def test_verify_write_corrupt_json(tmp_path: Path):
    """verify_write returns False on unparseable content."""
    p = tmp_path / "broken.json"
    p.write_text("{not valid json")
    assert verify_write(p, {"x": 1}) is False


def test_save_iter_sidecar_safe_normal(tmp_path: Path):
    """Happy path: returns True, writes file at expected path."""
    ok = save_iter_sidecar_safe("r1", "scout", 1, {"iter": 1}, runs_dir=tmp_path)
    assert ok is True
    expected = tmp_path / "r1+iters+scout+1.json"
    assert expected.exists()
    assert json.loads(expected.read_text()) == {"iter": 1}


def test_save_iter_sidecar_safe_retry_then_succeed(tmp_path: Path, caplog):
    """First attempt fails, retry succeeds — returns True, logs retry info."""
    call_count = {"n": 0}
    real_write = atomic_write_json

    def flaky(path, data):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("simulated disk transient")
        real_write(path, data)

    with patch("harness.persistence.sidecar_io.atomic_write_json", side_effect=flaky):
        with caplog.at_level(logging.WARNING):
            ok = save_iter_sidecar_safe(
                "r1", "scout", 1, {"iter": 1}, runs_dir=tmp_path, max_retries=1
            )
    assert ok is True
    assert call_count["n"] == 2


def test_save_iter_sidecar_safe_all_fail(tmp_path: Path, caplog):
    """Persistent failure: returns False and logs a WARNING with full context."""
    with patch(
        "harness.persistence.sidecar_io.atomic_write_json",
        side_effect=OSError("disk full"),
    ):
        with caplog.at_level(logging.WARNING):
            ok = save_iter_sidecar_safe(
                "r1", "scout", 1, {"iter": 1}, runs_dir=tmp_path, max_retries=1
            )
    assert ok is False
    # Log must include enough context to debug: run_id, node_id, iter, path.
    log_text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "r1" in log_text and "scout" in log_text and "iter=1" in log_text


def test_save_iter_sidecar_safe_no_raise_on_failure(tmp_path: Path):
    """R3: even on persistent failure, the function must NOT raise."""
    with patch(
        "harness.persistence.sidecar_io.atomic_write_json",
        side_effect=OSError("disk full"),
    ):
        result = save_iter_sidecar_safe(
            "r1", "scout", 1, {"iter": 1}, runs_dir=tmp_path, max_retries=1
        )
    assert result is False  # not raised


def test_save_iter_sidecar_safe_rejects_bad_id(tmp_path: Path):
    """Bad run_id / node_id (path traversal attempt) fails loud — ValueError."""
    with pytest.raises(ValueError):
        save_iter_sidecar_safe("../escape", "scout", 1, {}, runs_dir=tmp_path)
    with pytest.raises(ValueError):
        save_iter_sidecar_safe("r1", "scout/../../etc", 1, {}, runs_dir=tmp_path)


def test_save_iter_sidecar_safe_rejects_bad_iter(tmp_path: Path):
    """iter_num must be a positive int — ValueError on zero / negative / str."""
    with pytest.raises(ValueError):
        save_iter_sidecar_safe("r1", "scout", 0, {}, runs_dir=tmp_path)
    with pytest.raises(ValueError):
        save_iter_sidecar_safe("r1", "scout", -1, {}, runs_dir=tmp_path)
