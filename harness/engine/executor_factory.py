"""Per-node executor factory — dispatches by ``agent_def.executor`` field.

Phase A: ``LLMExecutor`` (pydantic-ai) is the only path that actually runs;
``ClaudeCodeExecutor`` is a fail-loud placeholder until Phase C.

新增 backend 的契约:
  1. 在 ``harness.core.agent.VALID_EXECUTORS`` 加白名单
  2. 实现一个 ``BaseExecutor`` 协议类（见 ``harness/engine/llm_executor.py``）
  3. 在此 ``make_executor`` 加 ``elif`` 分支

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
      - ``"pydantic-ai"`` (default) → ``LLMExecutor``
      - ``"claude-code"``            → ``ClaudeCodeExecutor`` (Phase A: 占位; Phase C: 实现)

    所有 backend 共享同一组 metadata 参数（bus/ids/ext_ctx/...）；
    ``pydantic_agent`` 仅 pydantic-ai 路径消费，claude-code 路径忽略。
    """
    backend = getattr(agent_def, "executor", "pydantic-ai")

    if backend == "claude-code":
        # 局部 import 避免顶层依赖；Phase A 的占位类足以让 import 链路通
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        logger.debug(
            "make_executor: dispatching agent %s to ClaudeCodeExecutor (Phase A scaffold)",
            agent_name,
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
        )

    if backend != "pydantic-ai":
        # 防御：Agent.__init__ 已经白名单校验，到这里的都是 bug
        raise ValueError(
            f"unknown executor backend {backend!r} on agent {agent_name!r}; "
            f"valid options: see harness.core.agent.VALID_EXECUTORS"
        )

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
