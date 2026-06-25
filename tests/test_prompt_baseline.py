"""Baseline generation + self-consistency test for prompt assembly.

Two responsibilities:
  1. ``--generate-baseline`` regenerates the golden fixtures from
     ``capture_prompt_baseline.legacy_assemble()``.
  2. Default run: asserts legacy_assemble() output matches the committed
     golden fixtures byte-for-byte. This guards against accidental drift of
     the CONTRACT before TASK 1 even starts.

After TASK 1 lands, add a second test comparing
``harness.prompts.assembler.assemble_static_prompt`` against these same
fixtures — that is the byte-for-byte equivalence proof.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from tests.capture_prompt_baseline import (
    FIXTURE_DIR,
    generate_fixtures,
    golden_inputs,
    legacy_assemble,
)


# Regenerate mode: set HARNESS_REGEN_BASELINE=1. Done in conftest collection
# so the consistency tests below validate freshly-written fixtures.
if os.environ.get("HARNESS_REGEN_BASELINE"):
    _d = generate_fixtures()
    print(f"\n[baseline] fixtures regenerated at {_d}")


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_legacy_matches_golden_fixture(name, body, result_type):
    """legacy_assemble() must reproduce the committed golden output exactly.

    This is the contract freeze: until TASK 1 extracts the logic, this test
    proves the COPY in capture_prompt_baseline.py still mirrors node_factory.
    If node_factory drifts, update legacy_assemble() + regenerate fixtures
    deliberately, not by accident.
    """
    fixture = FIXTURE_DIR / f"{name}.txt"
    assert fixture.exists(), (
        f"Missing baseline fixture {fixture}. "
        "Run: python -m pytest tests/test_prompt_baseline.py --generate-baseline"
    )
    expected = fixture.read_text(encoding="utf-8")
    actual = legacy_assemble(body, result_type)
    assert actual == expected, (
        f"legacy_assemble() drifted from golden fixture for case '{name}'.\n"
        "If node_factory.py changed intentionally, update legacy_assemble() in "
        "tests/capture_prompt_baseline.py and regenerate with --generate-baseline."
    )


def test_manifest_in_sync():
    """manifest.json must list every .txt fixture and match its sha256 prefix."""
    manifest_path = FIXTURE_DIR / "manifest.json"
    assert manifest_path.exists(), "manifest.json missing — regenerate baseline"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {e["case"]: e for e in manifest}

    fixture_files = {p.stem for p in FIXTURE_DIR.glob("*.txt")}
    assert set(entries) == fixture_files, (
        f"manifest cases {set(entries)} != fixture files {fixture_files}"
    )

    for name, body, result_type in golden_inputs():
        entry = entries[name]
        output = legacy_assemble(body, result_type)
        actual_sha8 = hashlib.sha256(output.encode("utf-8")).hexdigest()[:8]
        assert entry["sha256_first8"] == actual_sha8, (
            f"sha256 prefix mismatch for '{name}': "
            f"manifest={entry['sha256_first8']} actual={actual_sha8}"
        )
