"""TASK 1 acceptance test: assembler reproduces the legacy baseline exactly.

This is the byte-for-byte equivalence proof that extracting the prompt
assembly logic from node_factory into harness/prompts/assembler.py is a
behavior-preserving refactor. Every golden fixture generated from
``legacy_assemble()`` must be reproduced by ``assemble_static_prompt()``.

If this fails, the extraction drifted. Do NOT regenerate fixtures to silence
it — fix assembler to match the frozen contract.
"""
from __future__ import annotations

import pytest

from harness.prompts import assemble_static_prompt
from tests.capture_prompt_baseline import FIXTURE_DIR, golden_inputs


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_assembler_matches_legacy_baseline(name, body, result_type):
    """assemble_static_prompt() must equal the legacy golden output byte-for-byte."""
    expected = (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    actual = assemble_static_prompt(body, result_type)
    assert actual == expected, (
        f"assembler drifted from legacy baseline for case '{name}'.\n"
        f"expected {len(expected)} bytes, got {len(actual)} bytes.\n"
        "Do NOT regenerate the baseline — fix assembler.py to match the contract."
    )


def test_assembler_free_text_no_schema():
    """Free-text agents (result_type=None) get the body verbatim, no tail."""
    out = assemble_static_prompt("just a body", None)
    assert out == "just a body"


def test_assembler_does_not_mutate_input():
    """The caller's agent_md_body string must not be mutated."""
    body = "# Agent\n\nDoes things.\n"
    original = body
    assemble_static_prompt(body, None)
    assert body == original
