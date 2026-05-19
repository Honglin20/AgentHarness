"""Langfuse instrumentation — shared TracerProvider for pydantic_ai + Langfuse.

Without LANGFUSE_PUBLIC_KEY, init_langfuse() is a no-op and all instrumentation
calls degrade gracefully.
"""

from __future__ import annotations

import logging
import os
from contextlib import nullcontext as _nullcontext
from typing import Any

logger = logging.getLogger(__name__)

_langfuse: Any = None
_tracer_provider: Any = None


def init_langfuse() -> None:
    """Initialize Langfuse with shared TracerProvider.

    Reads LANGFUSE_PUBLIC_KEY from environment. No-op if not set or already
    initialized. Called once at server startup.
    """
    global _langfuse, _tracer_provider

    if _langfuse is not None:
        return

    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        logger.debug("LANGFUSE_PUBLIC_KEY not set — Langfuse disabled")
        return

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from langfuse import Langfuse

        _tracer_provider = TracerProvider()
        _langfuse = Langfuse(tracer_provider=_tracer_provider)
        logger.info("Langfuse initialized")
    except ImportError as e:
        logger.warning(f"Langfuse not available: {e}")


def get_tracer_provider() -> Any:
    """Get the shared TracerProvider, or None if Langfuse is disabled."""
    return _tracer_provider


def get_langfuse() -> Any:
    """Get the Langfuse client, or None if disabled."""
    return _langfuse


def start_observation(
    name: str,
    as_type: str = "span",
    input: Any = None,
) -> Any:
    """Start a Langfuse observation if available, otherwise a no-op context.

    Usage:
        with start_observation("analyzer", as_type="agent", input=ctx) as span:
            result = do_work()
            if span:
                span.update(output=result)
    """
    lf = _langfuse
    if lf is not None:
        return lf.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=input,
        )
    return _nullcontext()
