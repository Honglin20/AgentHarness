"""ClaudeCodeExecutor — per-node ``claude -p`` 子进程执行器（占位）。

Phase A: 仅声明实现 BaseExecutor 协议 + fail-loud run()，让 DAG 引擎
认识 ``executor: "claude-code"`` 字段但不能真的跑。

Phase C 会把 run() 替换成真正的 spawn / 流式读 / 翻译 / 提取链路。
设计参见 ``docs/plans/2026-06-25-claude-code-executor/detailed-design.md`` §6。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from harness.engine.llm_executor import AgentRunResult, BaseExecutor
from harness.engine.token_aggregator import TokenAggregator

logger = logging.getLogger(__name__)


class ClaudeCodeExecutor:
    """实现 ``BaseExecutor`` 协议；run() 在 Phase C 才有真实现。

    ``__init__`` 参数刻意与 ``LLMExecutor`` 平行（都接收 deps / event_bus /
    workflow_id / node_id / agent_name / ext_ctx / token_aggregator 等 metadata），
    以便 Phase C 把 spawn 逻辑填进来时不需要改 node_factory 的调用点。

    与 LLMExecutor 的差异：不需要 ``pydantic_agent``（claude-code 路径不用
    pydantic-ai Agent）；多一个 ``agent_def`` 引用（用于读 system prompt /
    retries / result_type 等）。
    """

    def __init__(
        self,
        agent_def: Any,
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
    ):
        self.agent_def = agent_def
        self._deps = deps
        self._bus = event_bus
        self._wid = workflow_id
        self._node_id = node_id
        self._agent_name = agent_name
        self._ext_ctx = ext_ctx
        self._check_interrupt = check_interrupt
        self._cancel_fn = cancel_fn
        self._token_aggregator = token_aggregator
        self._request_limit = request_limit
        # 占位：Phase C 实现时会从 stream-json 翻译出 tool_call 记录填进来
        self.tool_calls: list[dict[str, Any]] = []

    async def run(self, context: str) -> AgentRunResult:
        """Phase A 占位：fail-loud。Phase C 实现真正的 spawn + stream + 提取。"""
        raise NotImplementedError(
            "ClaudeCodeExecutor.run() is not implemented yet (Phase A scaffold). "
            f"Agent {self._agent_name!r} declared executor='claude-code' but the "
            "claude-code backend lands in Phase C. Either switch the agent back to "
            "executor='pydantic-ai' (default) or wait for Phase C completion. "
            "See docs/plans/2026-06-25-claude-code-executor/detailed-design.md §6."
        )

    def record_usage(self, usage_obj: Any) -> None:
        """Phase G 实现：把 claude result.usage 转成 token_aggregator 格式。"""
        # 占位：避免 node_factory 调用时 AttributeError；不静默吞错——日志 warn
        logger.debug(
            "ClaudeCodeExecutor.record_usage called pre-Phase-G; agent=%s ignored usage_obj=%r",
            self._agent_name, usage_obj,
        )

    def get_last_request_usage(self) -> dict[str, int]:
        """Phase G 实现：返回最近一次 claude 请求的 usage delta。"""
        return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


# 显式声明协议实现（runtime_checkable Protocol 用 isinstance 校验）
_BASE_EXECUTOR_CHECK = isinstance(
    ClaudeCodeExecutor(
        agent_def=None, deps=None, workflow_id="x", node_id="x", agent_name="x"
    ),
    BaseExecutor,
)
assert _BASE_EXECUTOR_CHECK, (
    "ClaudeCodeExecutor must satisfy BaseExecutor protocol — "
    "missing run/record_usage/get_last_request_usage/tool_calls"
)
