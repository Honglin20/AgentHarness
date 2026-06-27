"""Static system-prompt assembler.

Builds the static portion of an agent's system prompt from layered sources.
Extracted from ``harness/engine/node_factory.py`` (the ``augmented_prompt``
construction at lines ~147-165). The byte-level contract for the pydantic-ai
paradigm is frozen by ``tests/test_prompt_baseline.py``: ``assemble_static_prompt()``
with default ``executor="pydantic-ai"`` must reproduce every golden fixture exactly.

Paradigm split (P1-T2):
  - ``pydantic-ai`` paradigm — TodoTool MUST / final_result tool contracts;
        used by the pydantic-ai SDK executor (in-process tool dispatch).
  - ``minimal`` paradigm — no pydantic-ai-only tool contracts; used by CLI
        subprocess executors (claude-code / codex / opencode / ...) that
        bring their own tool protocol (MCP / function calls) and would
        otherwise be told to call non-existent tools.

Layers assembled:
  [base]    base working norms (paradigm-specific md file)
  [agent]   ``agent_md_body`` verbatim (domain logic)
  [output]  ``## Output Format`` + schema (only when result_type set;
            wording depends on paradigm)

The pydantic-ai output-format wording is deliberately identical to the
legacy inline formulation. Do NOT "improve" it without regenerating the
baseline fixtures — that is the regression detector.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from harness.engine.schema_utils import strip_schema

# ---------------------------------------------------------------------------
# Paradigm registry.
#
# Two prompt paradigms exist; every executor (builtin or user-registered via
# CliProfile in P3) must belong to exactly one. The paradigm dictates which
# base-md file is loaded and which output-format wording is appended.
# ---------------------------------------------------------------------------

#: Canonical paradigm identifiers. Adding a third paradigm is a framework-level
#: change — it requires a new base-md file + a new output-format template.
PROMPT_PARADIGMS: frozenset[str] = frozenset({"pydantic-ai", "minimal"})


#: Mapping from executor name → prompt paradigm. pydantic-ai is special (its
#: paradigm shares the name); every CLI executor defaults to "minimal" until
#: a CliProfile overrides it (P3-T1+).
_EXECUTOR_PARADIGM_OVERRIDES: dict[str, str] = {}


def register_executor_paradigm(executor: str, paradigm: str) -> None:
    """Override the paradigm an executor belongs to.

    Used by CliProfile registration (P3) to declare e.g. an executor that
    should follow the pydantic-ai prompt paradigm even though it spawns a
    subprocess. Default mapping covers builtin executors; overrides are
    idempotent (last-write-wins).
    """
    if paradigm not in PROMPT_PARADIGMS:
        raise ValueError(
            f"unknown paradigm {paradigm!r}; valid options: {sorted(PROMPT_PARADIGMS)}"
        )
    _EXECUTOR_PARADIGM_OVERRIDES[executor] = paradigm


def executor_to_paradigm(executor: str) -> str:
    """Map an executor name to its prompt paradigm.

    Rules:
      - ``"pydantic-ai"`` (builtin) → ``"pydantic-ai"`` paradigm
      - Anything else (including all CLI subprocess executors) → ``"minimal"``
      - CliProfile-registered overrides via ``register_executor_paradigm``
        take precedence (P3+).
    """
    if executor in _EXECUTOR_PARADIGM_OVERRIDES:
        return _EXECUTOR_PARADIGM_OVERRIDES[executor]
    if executor == "pydantic-ai":
        return "pydantic-ai"
    return "minimal"


# ---------------------------------------------------------------------------
# Base-layer content (paradigm-specific working norms).
#
# Loaded once per paradigm and cached (module-level, since the files ship
# with the package and never change within a process). lru_cache covers
# both paradigms; tests can .cache_clear() if they swap a file.
# ---------------------------------------------------------------------------

_BASE_MD_PATHS: dict[str, Path] = {
    "pydantic-ai": Path(__file__).resolve().parent / "base_pydantic.md",
    "minimal": Path(__file__).resolve().parent / "base_minimal.md",
}


@lru_cache(maxsize=len(_BASE_MD_PATHS))
def _load_base_layer(paradigm: str = "pydantic-ai") -> str:
    """Read and cache the base working-norms prompt for the given paradigm.

    Returns the file content with surrounding whitespace stripped. Unknown
    paradigm → raises ValueError (fail-loud). Missing file → returns "" so
    a corrupted install degrades gracefully rather than crashing every agent.
    """
    if paradigm not in _BASE_MD_PATHS:
        raise ValueError(
            f"unknown paradigm {paradigm!r}; valid options: {sorted(_BASE_MD_PATHS)}"
        )
    try:
        return _BASE_MD_PATHS[paradigm].read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Output-format sections (paradigm-specific wording).
#
# Both templates append the result_type schema. The pydantic-ai wording is
# frozen by baseline fixtures — DO NOT change without regenerating. The
# minimal wording is new in P1-T2 (no legacy baseline to protect).
# ---------------------------------------------------------------------------

#: pydantic-ai path: instructs the model to call the registered `final_result`
#: tool with the result_type schema. Frozen wording — baseline fixtures
#: assert byte-level stability.
_OUTPUT_FORMAT_PYDANTIC_TEMPLATE = (
    "\n\n## Output Format\n"
    "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n\n"
    "When the work is complete, **call the `final_result` tool** with arguments matching this schema:\n"
    "{schema}\n\n"
    "Do NOT emit the JSON as plain text — the framework only accepts a `final_result` "
    "tool call. If you previously emitted text or markdown and received an "
    "\"Invalid JSON\" reminder, switch immediately to calling the `final_result` tool "
    "with the fields shown above."
)


#: minimal path: instructs the model to respond with JSON matching the schema
#: directly. CLI backends (claude -p / codex / opencode) have no `final_result`
#: tool registered — referencing it would confuse the model.
_OUTPUT_FORMAT_MINIMAL_TEMPLATE = (
    "\n\n## Output Format\n"
    "When the work is complete, respond with a single JSON object matching this schema:\n"
    "{schema}\n\n"
    "Output ONLY the JSON object — no surrounding prose, no markdown fences. "
    "If a previous attempt was rejected for being malformed JSON, switch "
    "immediately to emitting a valid JSON object with the fields shown above."
)


def _output_format_section(result_type: Type[BaseModel], paradigm: str = "pydantic-ai") -> str:
    """Render the output-format section for a result_type under a paradigm.

    Returns the section WITHOUT a leading separator — it is appended to the
    agent body, which already provides the join point (``\\n\\n``).

    Raises ``ValueError`` on unknown paradigm (fail-loud, symmetric with
    ``_load_base_layer``). Caller is expected to pass a canonical paradigm
    via ``executor_to_paradigm``.
    """
    if paradigm == "pydantic-ai":
        template = _OUTPUT_FORMAT_PYDANTIC_TEMPLATE
    elif paradigm == "minimal":
        template = _OUTPUT_FORMAT_MINIMAL_TEMPLATE
    else:
        raise ValueError(
            f"unknown paradigm {paradigm!r}; valid options: {sorted(PROMPT_PARADIGMS)}"
        )
    schema = strip_schema(result_type.model_json_schema())
    return template.format(schema=json.dumps(schema, indent=2, ensure_ascii=False))


def assemble_static_prompt(
    agent_md_body: str,
    result_type: Type[BaseModel] | None,
    *,
    executor: str = "pydantic-ai",
) -> str:
    """Assemble the static system prompt for one agent.

    Layer order (first = seen first by the model):
      [base]    base working norms (paradigm-specific)
      [agent]   ``agent_md_body`` verbatim (domain logic)
      [output]  ``## Output Format`` + schema (only when result_type set;
                wording depends on paradigm)

    Parameters
    ----------
    agent_md_body
        The verbatim body of the agent's Markdown file (frontmatter stripped).
        Treated as opaque text — no parsing or mutation here.
    result_type
        The agent's structured output type, or None for free-text agents.
        When provided, a paradigm-specific ``## Output Format`` section is
        appended.
    executor
        Executor name (``agent_def.executor``). Determines the prompt
        paradigm via :func:`executor_to_paradigm`. Default ``"pydantic-ai"``
        keeps every legacy call site byte-level unchanged.

    Returns
    -------
    str
        The full static system prompt.

    Notes
    -----
    - The base layer is cached at module load (paradigm-md ships with the
      framework and is immutable within a process).
    - result_type schema derivation failures are NOT caught here — callers
      needing the lenient fallback should wrap this call.
    - An empty ``agent_md_body`` still gets the base prefix; an empty
      ``result_type``-free agent with empty body yields just the base layer.
    """
    paradigm = executor_to_paradigm(executor)
    parts: list[str] = []
    base = _load_base_layer(paradigm)
    if base:
        parts.append(base)
    if agent_md_body:
        parts.append(agent_md_body)
    prompt = "\n\n".join(parts)
    if result_type is not None:
        prompt += _output_format_section(result_type, paradigm)
    return prompt
