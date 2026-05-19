"""LangSmith instrumentation — auto-trace LangGraph + manual Pydantic AI spans.

Without LANGCHAIN_API_KEY, all instrumentation degrades to no-op.
LangGraph nodes are auto-traced by LangChain's callback system when
LANGCHAIN_TRACING_V2=true (set automatically).
"""

from __future__ import annotations

import logging
import os
from contextlib import nullcontext as _nullcontext
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None


def init_langsmith() -> None:
    """Initialize LangSmith tracing. No-op if LANGCHAIN_API_KEY not set."""
    global _client

    if _client is not None:
        return

    if not os.environ.get("LANGCHAIN_API_KEY"):
        logger.debug("LANGCHAIN_API_KEY not set — LangSmith disabled")
        return

    try:
        from langsmith import Client

        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        _client = Client()
        logger.info("LangSmith initialized")
    except ImportError as e:
        logger.warning(f"LangSmith not available: {e}")


def get_client() -> Any:
    """Get the LangSmith Client, or None if disabled."""
    return _client


def trace_agent(name: str, inputs: dict | None = None) -> Any:
    """Start a LangSmith trace for an agent's LLM execution.

    Usage:
        with trace_agent("analyzer", inputs={"context": ...}) as run:
            result = await agent.run(context)
            if run:
                run.end(outputs={"result": result.output})
    """
    if _client is None:
        return _nullcontext()

    try:
        from langsmith.run_helpers import trace

        return trace(
            name=name,
            run_type="llm",
            inputs=inputs or {},
        )
    except Exception:
        return _nullcontext()
