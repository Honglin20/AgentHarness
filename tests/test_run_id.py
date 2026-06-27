"""Unit tests for harness.persistence.run_id.

Covers: slug transformation, format compliance with _SAFE_ID_RE,
timestamp injection, and uniqueness across calls.
"""
from __future__ import annotations

import re
from datetime import datetime

from harness.persistence.run_id import _slugify, generate_run_id

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_slug_lowercases_and_collapses_separators():
    assert _slugify("NAS Workflow") == "nas-workflow"
    assert _slugify("Foo--Bar!!!") == "foo-bar"
    assert _slugify("adapter gen v2") == "adapter-gen-v2"


def test_slug_empty_inputs_fall_back():
    assert _slugify("") == "run"
    assert _slugify("   ") == "run"
    assert _slugify("!!!") == "run"
    assert _slugify(None) == "run"  # type: ignore[arg-type]


def test_slug_truncates_to_max_length():
    slug = _slugify("a" * 100)
    assert len(slug) == 30
    # Truncation should not leave a trailing '-'.
    assert slug == "a" * 30


def test_slug_trailing_separator_stripped_after_truncation():
    # "ab-ab-ab-..." truncated at 30 chars should not end mid-separator.
    slug = _slugify("ab-" * 50)
    assert not slug.endswith("-")
    assert _SAFE_ID_RE.match(slug)


def test_generate_run_id_matches_safe_id_regex():
    for name in ("nas", "MNIST Training", "adapter-gen", "", "weird/name!"):
        rid = generate_run_id(name)
        assert _SAFE_ID_RE.match(rid), f"{rid!r} failed regex for name={name!r}"


def test_generate_run_id_timestamp_format():
    rid = generate_run_id("nas", now=datetime(2026, 6, 27, 9, 49))
    assert rid.startswith("nas-20260627-0949-")
    suffix = rid.rsplit("-", 1)[1]
    assert len(suffix) == 6
    assert all(c in "0123456789abcdef" for c in suffix)


def test_generate_run_id_uses_slug_for_workflow_name():
    rid = generate_run_id("NAS Workflow", now=datetime(2026, 1, 1, 0, 0))
    assert rid.startswith("nas-workflow-20260101-0000-")


def test_generate_run_id_empty_name_uses_run_slug():
    rid = generate_run_id("", now=datetime(2026, 1, 1, 0, 0))
    assert rid.startswith("run-20260101-0000-")


def test_two_calls_produce_different_ids():
    a = generate_run_id("nas")
    b = generate_run_id("nas")
    assert a != b


def test_rerun_and_fresh_run_can_coexist_by_id_format():
    # Same workflow, different timestamps → lexicographically sortable.
    a = generate_run_id("nas", now=datetime(2026, 6, 27, 9, 49))
    b = generate_run_id("nas", now=datetime(2026, 6, 27, 10, 15))
    assert a < b  # earlier timestamp sorts first
