"""Per-node executor factory — dispatches by ``agent_def.executor`` field.

P3-T6: dispatch is now profile-registry-driven. ``pydantic-ai`` is special
(in-process, no CLI subprocess); every other registered executor name
goes through ``ClaudeCodeExecutor`` with the matching ``CliProfile``.
This lets operators register new CLI backends (opencode / codex / canary
claude builds) via ``harness/cli_profiles/`` without touching this factory.

新增 backend 的契约（post-P3）:
  1. 写一个 ``harness/cli_profiles/<name>.py`` 文件，导出 ``PROFILE: CliProfile``
  2. ensure translator + result_extractor cover the backend's output format
  3. (optional) project-level: ``./.harness/cli_profiles/<name>.py`` overrides builtin

For non-CLI backends (in-process like pydantic-ai), keep the ``elif``
form here — they do not have a CliProfile.

详细设计: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §4-§6
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from harness.engine.llm_executor import BaseExecutor, LLMExecutor
from harness.engine.token_aggregator import TokenAggregator

logger = logging.getLogger(__name__)


def make_executor(
    agent_def: Any,
    pydantic_agent: Any,
    deps: Any,
    *,
    event_bus: Any | None = None,
    workflow_id: str = "",
    node_id: str = "",
    agent_name: str = "",
    ext_ctx: Any | None = None,
    check_interrupt: Callable[[str, str], dict[str, Any] | None] | None = None,
    cancel_fn: Callable[[str], None] | None = None,
    token_aggregator: TokenAggregator | None = None,
    request_limit: int | None = None,
) -> BaseExecutor:
    """Dispatch to the right executor implementation based on ``agent_def.executor``.

    分派规则:
      - ``"pydantic-ai"`` (default) → ``LLMExecutor`` (in-process)
      - any other registered name → ``ClaudeCodeExecutor`` with the
        matching ``CliProfile`` (looked up via harness.engine.cli_profile.get_profile)

    所有 backend 共享同一组 metadata 参数（bus/ids/ext_ctx/...）；
    ``pydantic_agent`` 仅 pydantic-ai 路径消费，CLI 路径忽略。
    """
    backend = getattr(agent_def, "executor", "pydantic-ai")

    if backend == "pydantic-ai":
        return LLMExecutor(
            pydantic_agent,
            deps,
            event_bus=event_bus,
            workflow_id=workflow_id,
            node_id=node_id,
            agent_name=agent_name,
            ext_ctx=ext_ctx,
            check_interrupt=check_interrupt,
            cancel_fn=cancel_fn,
            token_aggregator=token_aggregator,
            request_limit=request_limit,
        )

    # CLI backend: look up the profile and pass it to ClaudeCodeExecutor.
    # Profile resolution lives in cli_profile.get_profile — clear errors
    # for unknown / disabled profiles (P3-T3 / P3-T9).
    from harness.engine.cli_profile import get_profile
    from harness.engine.claude_code_executor import ClaudeCodeExecutor

    try:
        profile = get_profile(backend)
    except KeyError as exc:
        raise ValueError(
            f"unknown executor {backend!r} on agent {agent_name!r}; "
            f"valid options: see harness.core.agent.VALID_EXECUTORS(). "
            f"Detail: {exc}"
        ) from exc
    except ValueError as exc:
        # Disabled profile — re-raise as ValueError so callers see the
        # disable reason in the message.
        raise ValueError(
            f"executor {backend!r} on agent {agent_name!r} is unavailable: {exc}"
        ) from exc

    logger.debug(
        "make_executor: dispatching agent %s to ClaudeCodeExecutor (profile=%s)",
        agent_name, profile.name,
    )
    return ClaudeCodeExecutor(
        agent_def=agent_def,
        deps=deps,
        event_bus=event_bus,
        workflow_id=workflow_id,
        node_id=node_id,
        agent_name=agent_name,
        ext_ctx=ext_ctx,
        check_interrupt=check_interrupt,
        cancel_fn=cancel_fn,
        token_aggregator=token_aggregator,
        request_limit=request_limit,
        profile=profile,
    )
