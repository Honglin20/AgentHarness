"""P1-T1: base.md split acceptance tests.

Locks the contract that:
  - ``base_pydantic.md`` is byte-level identical to the pre-split ``base.md``
    (so the pydantic-ai path is a behavior-preserving no-op).
  - ``base_minimal.md`` does NOT contain pydantic-ai-specific tool contracts
    (``TodoTool`` MUST / ``final_result`` tool / ``complete_remaining``).
  - The original ``base.md`` no longer exists — callers cannot accidentally
    load the un-split file.

These tests guard against accidental drift across P1-T2..P1-T4.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "harness" / "prompts"
BASE_PYDANTIC = PROMPTS_DIR / "base_pydantic.md"
BASE_MINIMAL = PROMPTS_DIR / "base_minimal.md"
LEGACY_BASE = PROMPTS_DIR / "base.md"


def _git_show_head(path: str) -> str:
    """Return file content at HEAD. Skips test if git unavailable / file
    not tracked at HEAD."""
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git HEAD content unavailable")
    return out.stdout


def test_base_pydantic_excludes_todo_tool_mandate():
    """Post-TODO-opt-in: base_pydantic.md must NOT mandate TodoTool as first action.

    The TodoTool is now opt-in (EXPLICIT tier). The base prompt must not tell
    agents to call TodoTool since most agents won't have it loaded. Agents that
    opt into TodoTool get todo guidance via the dynamic runtime_status layer.
    """
    content = BASE_PYDANTIC.read_text(encoding="utf-8")
    forbidden = ["Your first action MUST be `TodoTool(op='create'"]
    found = [w for w in forbidden if w in content]
    assert not found, (
        f"base_pydantic.md still mandates TodoTool as first action: {found}. "
        "TodoTool is now opt-in — the base prompt must not force it."
    )


def test_base_minimal_excludes_pydantic_ai_tool_contracts():
    """minimal path must NOT mention pydantic-ai-only tools / contracts."""
    content = BASE_MINIMAL.read_text(encoding="utf-8")
    forbidden = ["TodoTool", "final_result", "complete_remaining"]
    found = [w for w in forbidden if w in content]
    assert not found, (
        f"base_minimal.md contains pydantic-ai-specific terms: {found}. "
        "The minimal paradigm must not force these CLI-backends to call "
        "tools they don't have."
    )


def test_legacy_base_md_removed():
    """The un-split base.md must be gone so future callers cannot load it
    by accident. base_pydantic.md / base_minimal.md replace it."""
    assert not LEGACY_BASE.exists(), (
        f"{LEGACY_BASE} still exists — the split is incomplete. "
        "All callers must go through base_pydantic.md / base_minimal.md."
    )


def test_base_files_exist():
    """Sanity: both paradigm files must exist after the split."""
    assert BASE_PYDANTIC.exists(), f"missing {BASE_PYDANTIC}"
    assert BASE_MINIMAL.exists(), f"missing {BASE_MINIMAL}"


def test_assembler_loads_pydantic_base_by_default():
    """assembler.assemble_static_prompt (without executor kwarg) must still
    load base_pydantic.md. This protects every existing call site until
    P1-T3 wires the executor arg through."""
    from harness.prompts.assembler import _load_base_layer
    pydantic_content = _load_base_layer("pydantic-ai")
    default_content = _load_base_layer()
    assert pydantic_content == default_content, (
        "_load_base_layer() default must match pydantic-ai paradigm to keep "
        "untouched call sites behavior-preserving."
    )
