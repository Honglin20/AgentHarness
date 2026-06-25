"""Baseline snapshot for system-prompt assembly logic.

Purpose
-------
Captures the CURRENT (pre-refactor) behavior of the system-prompt assembly
logic that lives inline in ``harness/engine/node_factory.py``
(the ``augmented_prompt`` construction at lines ~147-165).

TASK 1 of the PROMPT refactor extracts that inline logic into
``harness/prompts/assembler.py``. That extraction must be a byte-for-byte
behavioral no-op. This module provides:

  - ``legacy_assemble()``: faithful COPY of the current logic (the contract).
  - ``golden_inputs()``: a matrix of realistic agent shapes.
  - ``generate_fixtures()``: writes golden outputs to tests/fixtures/prompt_baseline/.

Run via pytest (the project's pth setup resolves the local harness source
only under pytest's ``pythonpath=['.']``):

    python -m pytest tests/test_prompt_baseline.py --generate-baseline

The companion test ``test_prompt_baseline.py`` asserts any future
``assembler.assemble_static_prompt()`` reproduces these golden outputs.

Why a separate module (not inline in the test)?
  The legacy logic is the CONTRACT — it must be reviewable in isolation and
  must not drift via test refactorings. Keeping it here makes the "frozen
  pre-refactor behavior" explicit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from harness.core.types import AgentResult
from harness.engine.schema_utils import strip_schema

# ---------------------------------------------------------------------------
# Legacy assembly logic — COPY of node_factory.py:147-165 (do NOT improve).
# If node_factory changes before TASK 1 lands, update this in lock-step.
# ---------------------------------------------------------------------------

_LEGACY_OUTPUT_FORMAT_TEMPLATE = (
    "\n\n## Output Format\n"
    "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n\n"
    "When the work is complete, **call the `final_result` tool** with arguments matching this schema:\n"
    "{schema}\n\n"
    "Do NOT emit the JSON as plain text — the framework only accepts a `final_result` "
    "tool call. If you previously emitted text or markdown and received an "
    "\"Invalid JSON\" reminder, switch immediately to calling the `final_result` tool "
    "with the fields shown above."
)


def legacy_assemble(agent_md_body: str, result_type: Type[BaseModel] | None) -> str:
    """Faithful reproduction of node_factory's augmented_prompt construction.

    Returns the same string node_factory would feed to micro_agent.create()
    for the given (agent body, result_type) pair. result_type=None mirrors
    the free-text path (no schema tail appended).
    """
    augmented = agent_md_body
    if result_type is not None:
        schema = strip_schema(result_type.model_json_schema())
        augmented += _LEGACY_OUTPUT_FORMAT_TEMPLATE.format(
            schema=json.dumps(schema, indent=2, ensure_ascii=False)
        )
    return augmented


# ---------------------------------------------------------------------------
# Golden input matrix — realistic agent shapes from the real codebase.
# ---------------------------------------------------------------------------

_FREE_TEXT_BODY = (
    "# Scout\n\n"
    "You explore the codebase to locate the model class and train entry.\n\n"
    "## Constraints\n"
    "- Read-only: do not modify any files.\n"
)

_AGENT_RESULT_BODY = (
    "# Analyzer\n\n"
    "You analyze the project structure and report findings.\n"
)


class _BaselineCustomResult(BaseModel):
    """Stand-in for a domain result_type with varied field shapes.

    Mirrors NAS ProjectAnalysis complexity: required + optional + default +
    nullable fields, exercising strip_schema's anyOf/ null handling.
    """

    model_class: str
    model_module: str
    train_entry: str
    epochs_controllable: bool
    epochs_default: int | None = None
    weights_path: str = "NOT_FOUND"
    summary: str = ""


_CUSTOM_BODY = (
    "# Project Analyzer\n\n"
    "Detect user project structure. Output-only: never modify user files.\n\n"
    "## Detection order\n"
    "1. model_class via glob + grep\n"
    "2. train_entry\n"
)

# Body that already mentions final_result — ensures no stripping/dedup.
_SHADOW_BODY = (
    "# Reporter\n\n"
    "Write a report. Note: the framework calls `final_result` — match its schema.\n"
)

_EMPTY_BODY = ""


def golden_inputs() -> list[tuple[str, str, Type[BaseModel] | None]]:
    """Return (case_name, agent_md_body, result_type) tuples covering edge cases."""
    return [
        ("free_text", _FREE_TEXT_BODY, None),
        ("default_agent_result", _AGENT_RESULT_BODY, AgentResult),
        ("custom_result_type", _CUSTOM_BODY, _BaselineCustomResult),
        ("shadow_text", _SHADOW_BODY, AgentResult),
        ("empty_body", _EMPTY_BODY, AgentResult),
        ("empty_body_no_result", _EMPTY_BODY, None),
    ]


# ---------------------------------------------------------------------------
# Fixture generation.
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "prompt_baseline"


def generate_fixtures() -> Path:
    """Write one golden output file per input case. Returns FIXTURE_DIR.

    Each .txt is the exact string legacy_assemble() produces; manifest.json
    records case → result_type + byte size + sha256 prefix for quick audit.
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    for name, body, result_type in golden_inputs():
        output = legacy_assemble(body, result_type)
        (FIXTURE_DIR / f"{name}.txt").write_text(output, encoding="utf-8")
        manifest.append({
            "case": name,
            "result_type": "None" if result_type is None else result_type.__name__,
            "bytes": str(len(output.encode("utf-8"))),
            "sha256_first8": hashlib.sha256(
                output.encode("utf-8")
            ).hexdigest()[:8],
        })
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return FIXTURE_DIR
