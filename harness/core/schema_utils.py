"""Utilities for serializing/deserializing Pydantic BaseModel types via JSON Schema.

Used by Agent.to_dict/from_dict to persist custom result_type definitions
in workflow.json and agents_snapshot.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Type

from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)

# JSON Schema type → Python type
_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

_UNSET = ...  # sentinel for "no default" (Pydantic required field)


def _ensure_default(field_schema: dict, field_info: Any) -> Any:
    """Ensure a non-required field has a default value.

    For ``dict``/``list`` types without an explicit default, infers
    ``default_factory`` since Pydantic v2's JSON Schema omits this info.
    Other types get ``default=None``.
    """
    json_type = _effective_json_type(field_schema)
    factory = {"object": dict, "array": list}.get(json_type)

    if field_info is _UNSET:
        if factory:
            return Field(default_factory=factory)
        return Field(default=None)
    if isinstance(field_info, FieldInfo) and field_info.is_required():
        desc = field_info.description
        if factory:
            return Field(default_factory=factory, description=desc)
        return Field(default=None, description=desc)
    return field_info


def _effective_json_type(schema: dict) -> str | None:
    """Get the primary JSON Schema type, looking through ``anyOf``."""
    t = schema.get("type")
    if t:
        return t
    for v in schema.get("anyOf", []):
        t = v.get("type")
        if t and t != "null":
            return t
    return None


def safe_reconstruct_result_type(
    name: str | None, schema: dict | None
) -> Type[BaseModel] | None:
    """Reconstruct a result_type from stored name + schema, with fallback to None.

    Returns None (which Agent.__init__ converts to AgentResult) on any failure.
    Used by both Agent.from_dict and server reconstruction paths.
    """
    if not schema or not name:
        return None
    try:
        return schema_to_model(name, schema)
    except Exception:
        logger.warning(
            "Failed to reconstruct result_type '%s', falling back to AgentResult",
            name,
        )
        return None


def result_type_to_schema(result_type: Type[BaseModel]) -> dict | None:
    """Serialize a result_type class to a JSON Schema dict.

    Returns None if result_type is AgentResult (the default) to keep JSON clean.
    """
    from harness.api import AgentResult

    if result_type is AgentResult:
        return None
    return result_type.model_json_schema()


def schema_to_model(name: str, schema: dict) -> Type[BaseModel]:
    """Reconstruct a Pydantic BaseModel class from a JSON Schema dict.

    Handles flat models with basic types: str, int, float, bool, dict, list, Optional[T].
    Falls back to ``Any`` for unsupported types.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    defs = schema.get("$defs")

    if not properties:
        raise ValueError(f"Schema for '{name}' has no properties — cannot reconstruct")

    fields: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        py_type, field_info = _resolve_type(field_schema, defs)
        is_required = field_name in required

        if not is_required:
            py_type = Optional[py_type]  # type: ignore[assignment]
            field_info = _ensure_default(field_schema, field_info)

        fields[field_name] = (py_type, field_info)

    return create_model(name, **fields)


def _resolve_type(prop_schema: dict, defs: dict | None = None) -> tuple[type, Any]:
    """Convert a single JSON Schema property to ``(python_type, Field(...))``."""
    py_type: type = Any
    has_null = False

    # Handle anyOf (Optional / nullable)
    if "anyOf" in prop_schema:
        variants = prop_schema["anyOf"]
        non_null = [v for v in variants if v.get("type") != "null"]
        has_null = any(v.get("type") == "null" for v in variants)
        if len(non_null) == 1:
            py_type, _ = _resolve_type(non_null[0], defs)
        elif non_null:
            py_type = Any
    elif "$ref" in prop_schema and defs:
        ref_name = prop_schema["$ref"].split("/")[-1]
        ref_schema = defs.get(ref_name, {})
        py_type = schema_to_model(ref_name, {**ref_schema, "$defs": defs})
    else:
        json_type = prop_schema.get("type")
        if json_type in _TYPE_MAP:
            py_type = _TYPE_MAP[json_type]
        elif json_type == "object":
            py_type = dict
        elif json_type == "array":
            py_type = list
        elif json_type is None:
            py_type = Any

    if has_null:
        py_type = Optional[py_type]  # type: ignore[assignment]

    # Build Field with description and default
    description = prop_schema.get("description")
    default_sentinel = prop_schema.get("default", _UNSET)

    field_kwargs: dict[str, Any] = {}
    if description is not None:
        field_kwargs["description"] = description

    if default_sentinel is not _UNSET:
        # Mutable empty defaults → default_factory to avoid shared mutable
        if isinstance(default_sentinel, dict) and not default_sentinel:
            return py_type, Field(default_factory=dict, **field_kwargs)
        if isinstance(default_sentinel, list) and not default_sentinel:
            return py_type, Field(default_factory=list, **field_kwargs)
        return py_type, Field(default=default_sentinel, **field_kwargs)

    return py_type, Field(**field_kwargs) if field_kwargs else _UNSET
