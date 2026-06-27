"""P1-T2: assembler executor-paradigm acceptance tests.

Locks the contract that ``assemble_static_prompt`` dispatches by ``executor``
argument to the correct prompt paradigm:

  - ``executor="pydantic-ai"`` → pydantic-ai paradigm (byte-stable, frozen
    by ``test_prompt_baseline.py`` golden fixtures).
  - ``executor="claude-code"`` / ``"opencode"`` / ``"codex"`` / any unknown
    CLI executor → minimal paradigm (no ``final_result`` / ``TodoTool``
    references — those tools do not exist on CLI backends).
  - Custom override via ``register_executor_paradigm`` takes precedence.
  - Default ``executor="pydantic-ai"`` keeps every legacy call site
    byte-level unchanged (behavior-preserving).
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from harness.prompts.assembler import (
    PROMPT_PARADIGMS,
    _OUTPUT_FORMAT_MINIMAL_TEMPLATE,
    _OUTPUT_FORMAT_PYDANTIC_TEMPLATE,
    _load_base_layer,
    assemble_static_prompt,
    executor_to_paradigm,
    register_executor_paradigm,
)
from harness.prompts import assembler as assembler_mod
from tests.capture_prompt_baseline import golden_inputs


class _DemoResult(BaseModel):
    """Simple result type so output-format section is rendered."""
    summary: str
    score: int


# ---------------------------------------------------------------------------
# executor → paradigm mapping
# ---------------------------------------------------------------------------


def test_pydantic_ai_executor_maps_to_pydantic_paradigm():
    assert executor_to_paradigm("pydantic-ai") == "pydantic-ai"


@pytest.mark.parametrize("executor", ["claude-code", "opencode", "codex", "anything-else"])
def test_non_pydantic_executors_default_to_minimal(executor):
    """All CLI subprocess executors fall under the minimal paradigm."""
    assert executor_to_paradigm(executor) == "minimal"


def test_register_executor_paradigm_overrides_default():
    """A custom registration can move an executor across paradigms.

    Uses save/restore on the global override dict so parallel test runs
    (pytest-xdist) cannot race on each other's mutations.
    """
    import copy
    saved = copy.copy(assembler_mod._EXECUTOR_PARADIGM_OVERRIDES)
    try:
        register_executor_paradigm("claude-code", "pydantic-ai")
        assert executor_to_paradigm("claude-code") == "pydantic-ai"
        # Idempotent: same value twice does not error
        register_executor_paradigm("claude-code", "pydantic-ai")
        assert executor_to_paradigm("claude-code") == "pydantic-ai"
    finally:
        assembler_mod._EXECUTOR_PARADIGM_OVERRIDES.clear()
        assembler_mod._EXECUTOR_PARADIGM_OVERRIDES.update(saved)


def test_register_executor_paradigm_rejects_unknown_paradigm():
    with pytest.raises(ValueError, match="unknown paradigm"):
        register_executor_paradigm("xxx", "fictional-paradigm")


def test_prompt_paradigms_set_is_frozen():
    """The two-canonical-paradigms invariant: pydantic-ai + minimal."""
    assert PROMPT_PARADIGMS == frozenset({"pydantic-ai", "minimal"})


# ---------------------------------------------------------------------------
# Output format dispatch
# ---------------------------------------------------------------------------


def test_pydantic_output_format_contains_final_result_tool():
    """pydantic-ai path MUST instruct the model to call final_result tool."""
    section = assembler_mod._output_format_section(_DemoResult, "pydantic-ai")
    assert "call the `final_result` tool" in section, (
        "pydantic-ai output format lost its final_result tool instruction — "
        "regression vs baseline."
    )


def test_minimal_output_format_excludes_final_result_tool():
    """minimal path MUST NOT reference the final_result tool — CLI backends
    have no such tool registered; referencing it confuses the model."""
    section = assembler_mod._output_format_section(_DemoResult, "minimal")
    assert "final_result" not in section
    assert "TodoTool" not in section
    # Minimal template must still carry the schema
    assert '"properties"' in section or "summary" in section


def test_minimal_output_format_includes_schema_json():
    """Both paradigms must embed the result_type schema in the section."""
    pydantic_section = assembler_mod._output_format_section(_DemoResult, "pydantic-ai")
    minimal_section = assembler_mod._output_format_section(_DemoResult, "minimal")
    assert '"summary"' in pydantic_section
    assert '"summary"' in minimal_section


# ---------------------------------------------------------------------------
# End-to-end assembly per paradigm
# ---------------------------------------------------------------------------


def test_assemble_with_claude_code_executor_uses_minimal_base():
    """End-to-end: claude-code executor produces minimal-paradigm prompt."""
    out = assemble_static_prompt("# Greeter\n\nGreet the user.", _DemoResult, executor="claude-code")
    base_minimal = _load_base_layer("minimal")
    assert out.startswith(base_minimal), "minimal base not prepended for claude-code executor"
    assert "final_result" not in out, "claude-code path leaked final_result reference"
    assert "TodoTool" not in out, "claude-code path leaked TodoTool reference"
    assert "complete_remaining" not in out


def test_assemble_with_pydantic_ai_executor_uses_pydantic_base():
    """End-to-end: pydantic-ai executor produces pydantic-paradigm prompt.
    Frozen by baseline fixtures — byte-level stability is asserted elsewhere
    (test_prompt_baseline.py). Here we check paradigm dispatch only."""
    out = assemble_static_prompt("# Greeter\n\nGreet the user.", _DemoResult, executor="pydantic-ai")
    base_pydantic = _load_base_layer("pydantic-ai")
    assert out.startswith(base_pydantic)
    assert "call the `final_result` tool" in out


def test_assemble_default_executor_is_pydantic_ai():
    """Default executor kwarg must be pydantic-ai — every legacy call site
    that omits the arg stays byte-level unchanged."""
    out_default = assemble_static_prompt("body", None)
    out_explicit = assemble_static_prompt("body", None, executor="pydantic-ai")
    assert out_default == out_explicit


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_pydantic_path_byte_matches_legacy_baseline(name, body, result_type):
    """The pydantic-ai executor path (default) must reproduce the pre-P1-T2
    baseline byte-for-byte. This is the no-regression gate for the dispatch
    refactor — the dispatch must be transparent on the legacy path.

    Oracle: golden fixtures in tests/fixtures/prompt_baseline/<name>.txt were
    captured pre-split using the same pydantic-ai base content + the same
    output-format wording. The fixture stores ``legacy_assemble`` output
    (no base prefix); we prepend the pydantic-ai base using the same
    boundary the assembler uses."""
    from tests.capture_prompt_baseline import FIXTURE_DIR, legacy_assemble
    assembler_mod._load_base_layer.cache_clear()
    actual = assemble_static_prompt(body, result_type, executor="pydantic-ai")
    base = _load_base_layer("pydantic-ai")
    fixture = (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    # When body is non-empty, assembler joins base + body via "\n\n", then
    # appends output_format → base + "\n\n" + fixture.
    # When body is empty, assembler returns base alone, then appends
    # output_format (which itself starts with "\n\n") → base + fixture
    # because fixture already starts with the "\n\n" separator.
    if body:
        expected = f"{base}\n\n{fixture}" if base else fixture
    else:
        expected = f"{base}{fixture}" if base else fixture
    assert actual == expected, (
        f"pydantic-ai path drifted from pre-P1-T2 baseline for case '{name}'"
    )


# ---------------------------------------------------------------------------
# Fail-loud paths
# ---------------------------------------------------------------------------


def test_load_base_layer_unknown_paradigm_raises():
    """Unknown paradigm must fail loud — silent fallback would mask a typo
    in executor name and leave the agent without working norms."""
    with pytest.raises(ValueError, match="unknown paradigm"):
        _load_base_layer("fictional-paradigm")


def test_output_format_section_unknown_paradigm_raises():
    """Symmetric fail-loud contract: _output_format_section must also reject
    unknown paradigms. Silent fallback to minimal would mask a typo'd
    executor name on the result-format path."""
    with pytest.raises(ValueError, match="unknown paradigm"):
        assembler_mod._output_format_section(_DemoResult, "xxx-does-not-exist")
