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
from typing import Type

from pydantic import BaseModel

from harness.engine.schema_utils import strip_schema

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
        The full static system prompt. Byte-identical to the legacy
        ``node_factory`` ``augmented_prompt`` for the same inputs (proven by
        tests/test_prompt_baseline.py).

    Notes
    -----
    - base-layer injection (TASK 3) will prepend a base.md segment here.
      The function signature is designed to stay stable: base content will
      be resolved internally (cached file read), not added as a parameter.
    - result_type schema derivation failures are NOT caught here — the
      legacy code caught them at the call site (node_factory). Callers that
      need the lenient fallback should wrap this call.
    """
    prompt = agent_md_body
    if result_type is not None:
        prompt += _output_format_section(result_type)
    return prompt
