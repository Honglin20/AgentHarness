"""Schema validation utilities extracted from macro_graph for standalone testing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ValidationError


class ReviewDecision(BaseModel):
    """Default result_type for agents with conditional edges."""
    decision: Literal["pass", "fail"]
    reason: str
    score: float | None = None


def strip_schema(schema: dict) -> dict:
    """Remove fields from JSON Schema that add no value for LLMs.

    Strips: title, description (on the type itself, not on properties),
    anyOf [{type}, {type: null}] → inline "| null", default: null.
    Keeps: type, description (on properties), required, properties, items, enum.
    """
    if not isinstance(schema, dict):
        return schema

    out = {}
    for k, v in schema.items():
        if k in ("title", "default"):
            continue
        if k == "anyOf" and isinstance(v, list) and len(v) == 2:
            types = [e.get("type") for e in v if isinstance(e, dict)]
            has_ref = any("$ref" in e for e in v if isinstance(e, dict))
            if "null" in types and not has_ref:
                non_null = [t for t in types if t != "null" and t is not None]
                if non_null:
                    out["type"] = f"{non_null[0]} | null"
                    continue
        if k == "description" and "properties" in schema:
            # Skip top-level description (class docstring), keep property descriptions
            continue
        if isinstance(v, dict):
            out[k] = strip_schema(v)
        elif isinstance(v, list):
            out[k] = [strip_schema(i) for i in v]
        else:
            out[k] = v
    return out


def validate_output(output, result_type):
    """Validate agent output against its result_type.

    Returns None if valid, or an error string if validation fails.
    """
    if result_type is None:
        return None
    if output is None:
        return "Agent produced no output (interrupted or failed)"
    if not isinstance(output, BaseModel):
        return f"Expected {result_type.__name__}, got {type(output).__name__}"
    try:
        output.model_validate(output.model_dump())
    except ValidationError as e:
        return f"Output validation failed: {e}"
    return None
