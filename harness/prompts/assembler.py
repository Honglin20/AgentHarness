"""Static system-prompt assembler.

Builds the static portion of an agent's system prompt from layered sources.
Extracted verbatim from ``harness/engine/node_factory.py`` (the
``augmented_prompt`` construction at lines ~147-165) — TASK 1 is a pure
behavior-preserving refactor. The byte-level contract is frozen by
``tests/test_prompt_baseline.py``: ``assemble_static_prompt()`` must
reproduce every golden fixture exactly.

Layers assembled (TASK 1 scope — base layer added in TASK 3):
  - agent_md_body : the agent's domain prompt (caller-supplied, verbatim)
  - output format : appended only when result_type is provided; tells the
                    model to call the ``final_result`` tool with the
                    result_type's JSON schema.

The output-format wording is deliberately identical to the legacy inline
formulation. Do NOT "improve" it here without regenerating the baseline
fixtures — that is the regression detector.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from harness.engine.schema_utils import strip_schema

# ---------------------------------------------------------------------------
# Base-layer content (cross-agent working norms).
#
# Loaded once from harness/prompts/base.md and cached (module-level, since
# the file ships with the package and never changes within a process). A
# process-level cache is correct here: base.md is framework-shipped, not
# user-editable at runtime. The lru_cache wraps a function so tests can
# clear it if they swap the file.
# ---------------------------------------------------------------------------

_BASE_MD_PATH = Path(__file__).resolve().parent / "base.md"


@lru_cache(maxsize=1)
def _load_base_layer() -> str:
    """Read and cache the base working-norms prompt.

    Returns the file content with surrounding whitespace stripped. If the
    file is somehow missing, returns "" so assembly degrades gracefully to
    the legacy (base-less) behavior rather than crashing every agent.
    """
    try:
        return _BASE_MD_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

# ---------------------------------------------------------------------------
# Output-format section.
#
# Frozen wording — matches node_factory.py:147-165 byte-for-byte. Changing
# this string changes the byte-level baseline; do so deliberately via
# tests/capture_prompt_baseline.py regeneration.
# ---------------------------------------------------------------------------
_OUTPUT_FORMAT_TEMPLATE = (
    "\n\n## Output Format\n"
    "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n\n"
    "When the work is complete, **call the `final_result` tool** with arguments matching this schema:\n"
    "{schema}\n\n"
    "Do NOT emit the JSON as plain text — the framework only accepts a `final_result` "
    "tool call. If you previously emitted text or markdown and received an "
    "\"Invalid JSON\" reminder, switch immediately to calling the `final_result` tool "
    "with the fields shown above."
)


def _output_format_section(result_type: Type[BaseModel]) -> str:
    """Render the output-format section for a result_type.

    Returns the section WITHOUT a leading separator — it is appended to the
    agent body, which already provides the join point (``\\n\\n``). Caller
    is responsible for concatenation order.
    """
    schema = strip_schema(result_type.model_json_schema())
    return _OUTPUT_FORMAT_TEMPLATE.format(
        schema=json.dumps(schema, indent=2, ensure_ascii=False)
    )


def assemble_static_prompt(
    agent_md_body: str,
    result_type: Type[BaseModel] | None,
) -> str:
    """Assemble the static system prompt for one agent.

    Layer order (first = seen first by the model):
      [base]    base working norms (harness/prompts/base.md)
      [agent]   ``agent_md_body`` verbatim (domain logic)
      [output]  ``## Output Format`` + schema (only when result_type set)

    Parameters
    ----------
    agent_md_body
        The verbatim body of the agent's Markdown file (frontmatter stripped).
        Treated as opaque text — no parsing or mutation here.
    result_type
        The agent's structured output type, or None for free-text agents.
        When provided, an ``## Output Format`` section is appended instructing
        the model to call the ``final_result`` tool with the type's schema.

    Returns
    -------
    str
        The full static system prompt.

    Notes
    -----
    - The base layer is cached at module load (base.md ships with the
      framework and is immutable within a process).
    - result_type schema derivation failures are NOT caught here — callers
      needing the lenient fallback should wrap this call.
    - An empty ``agent_md_body`` still gets the base prefix; an empty
      ``result_type``-free agent with empty body yields just the base layer.
    """
    parts: list[str] = []
    base = _load_base_layer()
    if base:
        parts.append(base)
    if agent_md_body:
        parts.append(agent_md_body)
    prompt = "\n\n".join(parts)
    if result_type is not None:
        prompt += _output_format_section(result_type)
    return prompt
