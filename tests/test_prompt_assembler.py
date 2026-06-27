"""Assembler verification: pure-logic contract + base-layer prefix.

Two contracts coexist here:

1. The base layer (TASK 3) is a PURE PREFIX: with base.md loaded,
   ``assemble_static_prompt(body, rt) == base + "\n\n" + legacy_assemble(body, rt)``
   for every input. This proves the output-format logic is byte-identical to
   the pre-refactor inline code — the only change is the base prefix.

2. With the base layer disabled (monkeypatched to ""), the assembler must
   reproduce the legacy golden fixtures byte-for-byte. This is the strict
   TASK 1 regression gate, kept active so a future base-loading bug cannot
   silently corrupt the output-format section.

If (1) drifts, the base separator or output-format wording changed.
If (2) drifts, the core extraction itself changed. Fix, don't regenerate.
"""
from __future__ import annotations

import pytest

from harness.prompts import assemble_static_prompt
from harness.prompts import assembler as assembler_mod
from tests.capture_prompt_baseline import FIXTURE_DIR, golden_inputs, legacy_assemble


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_assembler_equals_base_plus_legacy(name, body, result_type, monkeypatch):
    """The base layer is a clean prefix: stripping it yields the no-base output.

    For non-empty bodies this is exactly ``base + "\\n\\n" + no_base_output``.
    For empty bodies the no-base output may start with the output-format
    section's own leading separator, so we strip at most one ``\\n\\n``
    boundary. The assertion: there EXISTS a single clean split point where
    the suffix equals the no-base output.
    """
    # No-base output (oracle).
    assembler_mod._load_base_layer.cache_clear()
    monkeypatch.setattr(assembler_mod, "_load_base_layer", lambda *a, **kw: "")
    without_base = assemble_static_prompt(body, result_type)

    # Base-on output (real).
    monkeypatch.undo()
    assembler_mod._load_base_layer.cache_clear()
    with_base = assemble_static_prompt(body, result_type)

    base = assembler_mod._load_base_layer()
    if not base:
        assert with_base == without_base
        return

    # The base prefix must be present, and removing it (plus one separator)
    # must leave the no-base output. Try the canonical "\n\n" join first.
    if with_base == f"{base}\n\n{without_base}":
        return
    # Empty-body fallback: without_base may carry a leading "\n\n" from the
    # output-format section; the assembler joins base directly to it.
    if with_base == f"{base}{without_base}":
        return
    raise AssertionError(
        f"base prefix not cleanly separable for '{name}'.\n"
        f"with_base[-40:]={with_base[-40:]!r}\n"
        f"base[-20:]={base[-20:]!r}\n"
        f"without_base[:40)]={without_base[:40]!r}"
    )


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_assembler_without_base_matches_legacy(name, body, result_type, monkeypatch):
    """With base disabled: byte-identical to legacy golden fixture."""
    # Clear the real cache BEFORE patching (after patch, the name points at a
    # plain lambda with no cache_clear).
    assembler_mod._load_base_layer.cache_clear()
    monkeypatch.setattr(assembler_mod, "_load_base_layer", lambda *a, **kw: "")
    expected = (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    actual = assemble_static_prompt(body, result_type)
    assert actual == expected, (
        f"core assembly drifted from legacy baseline for '{name}'."
    )


def test_assembler_free_text_no_schema(monkeypatch):
    """Free-text agents (result_type=None) get base + body verbatim, no schema tail."""
    assembler_mod._load_base_layer.cache_clear()
    monkeypatch.setattr(assembler_mod, "_load_base_layer", lambda *a, **kw: "")
    out = assemble_static_prompt("just a body", None)
    assert out == "just a body"


def test_assembler_does_not_mutate_input():
    """The caller's agent_md_body string must not be mutated."""
    body = "# Agent\n\nDoes things.\n"
    assemble_static_prompt(body, None)
    assert body == "# Agent\n\nDoes things.\n"


def test_base_layer_prepended_before_agent_body():
    """Base content must appear before the agent body in the output."""
    out = assemble_static_prompt("# My Agent\n\nDomain task.", None)
    base = assembler_mod._load_base_layer()
    if base:
        assert out.startswith(base)
        assert "# My Agent" in out
        assert out.index(base) < out.index("# My Agent")


def test_base_layer_loaded_nonempty():
    """base.md must exist and be non-empty (otherwise agents lose the norms)."""
    base = assembler_mod._load_base_layer()
    assert base, "base.md is empty or missing — every agent loses working norms"
