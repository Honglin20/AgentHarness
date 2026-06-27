"""P1-T4: minimal-paradigm baseline fixture + ask_user_demo prompt-content tests.

Two responsibilities:
  1. ``minimal_assemble()`` must reproduce committed golden fixtures in
     ``tests/fixtures/prompt_baseline_minimal/`` byte-for-byte. This locks
     the minimal output-format wording against accidental drift.
  2. ``assemble_static_prompt(..., executor='claude-code')`` output must
     match the minimal-paradigm oracle (base_minimal + minimal body) — the
     regression gate for ADR Decision 1.

Plus an end-to-end-style mock test simulating ask_user_demo/greeter:
given the real agent MD body + result_type=None, the assembled prompt must
NOT contain ``final_result`` / ``TodoTool`` strings (the user-acceptance
criterion for P1-T4).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from harness.prompts.assembler import (
    _load_base_layer,
    assemble_static_prompt,
)
from tests.capture_prompt_baseline import (
    MINIMAL_FIXTURE_DIR,
    golden_inputs,
    minimal_assemble,
)


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_minimal_assemble_matches_golden_fixture(name, body, result_type):
    """minimal_assemble() must reproduce committed minimal fixtures byte-level."""
    fixture = MINIMAL_FIXTURE_DIR / f"{name}.txt"
    assert fixture.exists(), (
        f"Missing minimal baseline fixture {fixture}. "
        "Run: HARNESS_REGEN_BASELINE=1 python -m pytest tests/test_prompt_baseline.py"
    )
    expected = fixture.read_text(encoding="utf-8")
    actual = minimal_assemble(body, result_type)
    assert actual == expected, (
        f"minimal_assemble() drifted from golden fixture for case '{name}'.\n"
        "If assembler.py minimal template changed intentionally, update "
        "minimal_assemble() in tests/capture_prompt_baseline.py and regenerate."
    )


def test_minimal_manifest_in_sync():
    """manifest.json must list every .txt fixture and match sha256 prefix."""
    manifest_path = MINIMAL_FIXTURE_DIR / "manifest.json"
    assert manifest_path.exists(), "minimal manifest.json missing — regenerate"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {e["case"]: e for e in manifest}

    fixture_files = {p.stem for p in MINIMAL_FIXTURE_DIR.glob("*.txt")}
    assert set(entries) == fixture_files, (
        f"manifest cases {set(entries)} != fixture files {fixture_files}"
    )

    for name, body, result_type in golden_inputs():
        entry = entries[name]
        output = minimal_assemble(body, result_type)
        actual_sha8 = hashlib.sha256(output.encode("utf-8")).hexdigest()[:8]
        assert entry["sha256_first8"] == actual_sha8, (
            f"sha256 prefix mismatch for '{name}': "
            f"manifest={entry['sha256_first8']} actual={actual_sha8}"
        )


@pytest.mark.parametrize("name,body,result_type", golden_inputs())
def test_assemble_static_prompt_minimal_matches_oracle(name, body, result_type):
    """assemble_static_prompt(executor='claude-code') must produce
    base_minimal + minimal body — the ADR Decision 1 contract."""
    actual = assemble_static_prompt(body, result_type, executor="claude-code")
    base = _load_base_layer("minimal")
    oracle_no_base = minimal_assemble(body, result_type)
    if body:
        expected = f"{base}\n\n{oracle_no_base}" if base else oracle_no_base
    else:
        expected = f"{base}{oracle_no_base}" if base else oracle_no_base
    assert actual == expected, (
        f"claude-code path drifted from minimal oracle for case '{name}'"
    )


# ---------------------------------------------------------------------------
# P1-T4 user acceptance: ask_user_demo prompt content
# ---------------------------------------------------------------------------

# Excerpt of workflows/_shared/workflows/ask_user_demo/agents/greeter.md body
# (frontmatter stripped). Reproduced here so the test does not depend on
# workflow file resolution at test time.
_ASK_USER_DEMO_GREETER_BODY = """# Greeter

You are a friendly greeter. Your ONLY task is to ask the user a single-choice question using `ask_user`.

CRITICAL: Your very first action MUST be to call the `ask_user` tool. Do NOT write any text before calling it.

After receiving the answer, output a JSON with "language" (the user's choice) and "greeting" (a short welcome in that language)."""


def test_ask_user_demo_greeter_prompt_excludes_pydantic_ai_contracts():
    """USER ACCEPTANCE (P1-T4): the prompt fed to claude -p for
    ask_user_demo/greeter must NOT contain pydantic-ai-only contracts
    (TodoTool / final_result / complete_remaining). The CLI backend has no
    such tools; referencing them confuses the model and was the original
    cause of greeter not calling ask_user."""
    prompt = assemble_static_prompt(
        _ASK_USER_DEMO_GREETER_BODY,
        result_type=None,
        executor="claude-code",
    )
    forbidden = ["TodoTool", "final_result", "complete_remaining"]
    found = [w for w in forbidden if w in prompt]
    assert not found, (
        f"ask_user_demo greeter prompt leaked pydantic-ai contracts: {found}"
    )


def test_ask_user_demo_greeter_prompt_includes_minimal_base():
    """USER ACCEPTANCE (P1-T4): the prompt must include the minimal-paradigm
    base working norms so the model still gets narration / failure-handling
    guidance even on the CLI backend."""
    prompt = assemble_static_prompt(
        _ASK_USER_DEMO_GREETER_BODY,
        result_type=None,
        executor="claude-code",
    )
    base_minimal = _load_base_layer("minimal")
    assert base_minimal, "base_minimal.md missing — every CLI agent loses norms"
    assert prompt.startswith(base_minimal), (
        "minimal base not prepended to ask_user_demo greeter prompt"
    )


def test_ask_user_demo_greeter_prompt_includes_agent_body():
    """USER ACCEPTANCE (P1-T4): the agent-specific body (with the actual
    ask_user tool instruction) must survive the assembly verbatim — base
    layer must not shadow or truncate the agent MD body."""
    prompt = assemble_static_prompt(
        _ASK_USER_DEMO_GREETER_BODY,
        result_type=None,
        executor="claude-code",
    )
    assert "ask_user" in prompt, "agent body's ask_user reference dropped"
    assert "CRITICAL: Your very first action MUST be to call the `ask_user` tool" in prompt
