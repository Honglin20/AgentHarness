"""ClaudeCodeExecutor — per-node ``claude -p`` 子进程执行器（Phase C 实现）。

工作流：
  1. 构造 ClaudeSpawnConfig（prompt + system prompt + 工具白名单）
  2. spawn claude 子进程（stdin 注入 prompt）
  3. 流式读 stdout 行 → JSON parse → translate → emit 到 event_bus
  4. 等子进程退出；exit_code != 0 抛 RuntimeError
  5. 从最后一条 result 事件提取 ``result.result`` 字段
  6. 构造 duck-type AgentRunResult 返回（agent_run.result.output = 提取的内容）

接口与 LLMExecutor 完全平行（实现 BaseExecutor 协议），node_factory 不需要
知道是 pydantic-ai 还是 claude-code。

Phase D 起会通过 mcp_config_path 接入 harness MCP server（ask_user 等桥接工具）。
Phase E 起会通过 session_id + --resume 支持 schema retry。

设计参考: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §6
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from harness.engine.llm_executor import AgentRunResult, BaseExecutor
from harness.engine.token_aggregator import TokenAggregator
from harness.engine._claude_subprocess import ClaudeRunResult, ClaudeSpawnConfig, run_claude
from harness.extensions.bus import safe_emit
from harness.translator import TranslateContext, TranslatedEvent, translate

logger = logging.getLogger(__name__)


# 翻译器会 emit 这几类生命周期事件，但 node_factory 已经有自己的
# node.started/completed/failed emit 链路（含 attempt/iteration/io_data 等更全的字段），
# 所以 ClaudeCodeExecutor 内部跳过这些，避免重复 emit。
_LIFECYCLE_EVENTS_NOT_EMIT: frozenset[str] = frozenset({
    "node.started",
    "node.completed",
    "node.failed",
})


# ---------------------------------------------------------------------------
# Duck-type shims — 让 ClaudeCodeExecutor.run 返回的对象满足 node_factory
# 对 pydantic-ai AgentRun 的最小依赖（agent_run.result.output + agent_run.usage）
# ---------------------------------------------------------------------------


@dataclass
class _ClaudeUsage:
    """duck-type: pydantic_ai.usage.Usage / RunUsage 最小子集。

    node_factory.line 487-509 读取 input_tokens / output_tokens / total_tokens /
    cache_read_tokens 字段。requests/tool_calls 也填上以兼容 pydantic-ai 的 Usage。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    requests: int = 1
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class _ClaudeResult:
    """duck-type: AgentRun.result。``output`` 是 pydantic 模型或 str。"""

    output: Any


@dataclass
class _ClaudeAgentRun:
    """duck-type: AgentRun（含 .result.output + .usage）。"""

    result: _ClaudeResult
    usage: _ClaudeUsage
    new_messages: list = None  # type: ignore[assignment]
    all_messages: list = None  # type: ignore[assignment]
    metadata: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.new_messages is None:
            self.new_messages = []
        if self.all_messages is None:
            self.all_messages = []
        if self.metadata is None:
            self.metadata = {}


# ---------------------------------------------------------------------------
# ClaudeCodeExecutor
# ---------------------------------------------------------------------------


class ClaudeCodeExecutor:
    """实现 ``BaseExecutor`` 协议；通过 ``claude -p`` 子进程执行 agent MD。

    ``__init__`` 参数与 ``LLMExecutor`` 平行（都接收 metadata），但额外需要
    ``agent_def``（读 system prompt / retries / tools 列表）。
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
        # Claude-specific:
        cli_path: str = "claude",
        timeout_s: float | None = None,
        mcp_config_path: Any | None = None,
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
        self._cli_path = cli_path
        self._timeout_s = timeout_s
        self._mcp_config_path = mcp_config_path

        # Per-run state（每次 run() 重置）
        self.tool_calls: list[dict[str, Any]] = []
        self._last_input: int = 0
        self._last_output: int = 0
        self._last_cache_hit: int = 0
        self._cumulative_input: int = 0
        self._cumulative_output: int = 0
        self._cumulative_cache_hit: int = 0
        self._final_result_text: str | None = None
        self._last_ttft_ms: int | None = None

    # ------------------------------------------------------------------
    # Public API — BaseExecutor 协议
    # ------------------------------------------------------------------

    async def run(self, context: str) -> AgentRunResult:
        """spawn claude, stream-translate-emit, 返回 duck-type AgentRunResult。

        Raises:
            RuntimeError: claude 子进程 exit_code != 0 或超时
        """
        # 重置 per-run state（万一同一实例被重试逻辑复用）
        self._reset_run_state()
        t0 = time.time()

        cfg = self._build_spawn_config(context)
        ctx = self._build_translate_ctx()

        # 把 stdout 每行喂翻译器，再 emit
        async def on_line(line: str) -> None:
            await self._handle_stdout_line(line, ctx)

        # check_interrupt 钩子：让 WS 中断能取消 claude 子进程
        # 当前实现：spawn 期间不主动 check（pydantic-ai 路径在 iter 中 check）；
        # Phase G 加精细 cancel 支持

        claude_result = await run_claude(cfg, on_line=on_line, timeout=self._timeout_s)
        elapsed_ms = int((time.time() - t0) * 1000)

        if claude_result.exit_code != 0:
            raise RuntimeError(
                f"claude subprocess exited code={claude_result.exit_code} "
                f"(timed_out={claude_result.timed_out}); stderr tail: "
                f"{claude_result.stderr[-500:]!r}"
            )

        # result_text 为空说明 claude 没产出 result 事件（异常情况）
        if self._final_result_text is None:
            raise RuntimeError(
                f"claude exited 0 but emitted no result event; "
                f"stderr tail: {claude_result.stderr[-500:]!r}"
            )

        # 构造 AgentRunResult（agent_run duck-type 让 node_factory 能正常消费）
        usage = _ClaudeUsage(
            input_tokens=self._cumulative_input,
            output_tokens=self._cumulative_output,
            cache_read_tokens=self._cumulative_cache_hit,
            requests=1,
            tool_calls=len(self.tool_calls),
        )
        agent_run = _ClaudeAgentRun(
            result=_ClaudeResult(output=self._final_result_text),
            usage=usage,
        )
        return AgentRunResult(agent_run=agent_run, stop_regen=None, ttft_ms=self._last_ttft_ms)

    def record_usage(self, usage_obj: Any) -> None:
        """node_factory.line 468 调用。我们已经在 run() 里累计，这里 no-op。"""
        # 故意空：claude-code 路径的 usage 在 run() 内部从 result.usage 直接拿；
        # node_factory 调 record_usage 是 pydantic-ai 路径的累计接口，对 claude-code
        # 无意义（agent_run.usage 已经是最终值）。
        logger.debug(
            "ClaudeCodeExecutor.record_usage noop (usage tracked internally); agent=%s",
            self._agent_name,
        )

    def get_last_request_usage(self) -> dict[str, int]:
        """node_factory.line 487 调用，期望返回 {last_input, last_output, last_cache_hit}。"""
        return {
            "last_input": self._last_input,
            "last_output": self._last_output,
            "last_cache_hit": self._last_cache_hit,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _reset_run_state(self) -> None:
        """每次 run() 开始时清空 per-run 累计变量。"""
        self.tool_calls = []
        self._last_input = 0
        self._last_output = 0
        self._last_cache_hit = 0
        self._cumulative_input = 0
        self._cumulative_output = 0
        self._cumulative_cache_hit = 0
        self._final_result_text = None
        self._last_ttft_ms = None

    def _build_spawn_config(self, context: str) -> ClaudeSpawnConfig:
        """从 agent_def + context 构造 spawn 配置。"""
        # system prompt: agent MD 内容（deps 应提供）
        system_prompt = self._resolve_system_prompt()

        allowed_tools = self._resolve_allowed_tools()

        return ClaudeSpawnConfig(
            prompt=context,
            mcp_config_path=self._mcp_config_path,
            allowed_tools=allowed_tools,
            append_system_prompt=system_prompt,
            cli_path=self._cli_path,
        )

    def _resolve_system_prompt(self) -> str | None:
        """从 agent_def / deps 提取 agent MD 内容作为 system prompt。"""
        # 优先 deps.agent_md_content（如果存在）
        deps = self._deps
        if deps is not None:
            for attr in ("agent_md_content", "system_prompt", "agent_prompt"):
                v = getattr(deps, attr, None)
                if v:
                    return v
        # 退而求其次：agent_def 上挂的 prompt（如果有）
        if self.agent_def is not None:
            for attr in ("prompt", "md_content", "system_prompt"):
                v = getattr(self.agent_def, attr, None)
                if v:
                    return v
        return None

    def _resolve_allowed_tools(self) -> list[str] | None:
        """从 agent_def.tools 提取白名单；None = claude 自选。"""
        if self.agent_def is None:
            return None
        tools = getattr(self.agent_def, "tools", None)
        if not tools:
            return None
        # agent_def.tools 是 harness 工具名（bash/read/...），需要映射到 claude 工具名
        # Phase C 简化：只透传，让用户/agent MD 自己保证名字对（claude 默认接受
        # 内置工具名首字母大写形式：Bash/Read/Edit/Write/Grep/Glob）
        # Phase D 实现工具桥接后会加 mcp__* 前缀映射
        return list(tools)

    def _build_translate_ctx(self) -> TranslateContext:
        return TranslateContext(
            node_id=self._node_id,
            agent_name=self._agent_name,
            iteration=1,  # Phase G 加精细 iteration tracking
            attempt=1,
        )

    async def _handle_stdout_line(self, line: str, ctx: TranslateContext) -> None:
        """每行 stdout: json parse → translate → emit + 抽取 usage/result/tool_calls。"""
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("non-JSON stdout line ignored: %r", line[:200])
            return

        # 在翻译前抽取 result 事件的关键字段（翻译器也抽，但 executor 要存原始值）
        self._extract_pre_translate(raw)

        events = translate(raw, ctx)
        for ev in events:
            self._track_post_translate(ev)
            self._emit(ev)

    def _extract_pre_translate(self, raw: dict) -> None:
        """从原始 stream-json 提取 executor 需要的累计字段（result/usage）。

        翻译器把 result.usage 转成 token_usage dict 用于 emit；但 executor 还要
        把 input/output/cache 累计起来供 get_last_request_usage() 用。
        """
        if raw.get("type") != "result":
            return

        # 提取最终 result.result 文本（Phase E 会做 JSON parse + schema 校验）
        if raw.get("result") is not None:
            self._final_result_text = str(raw["result"])

        usage = raw.get("usage") or {}
        if usage:
            self._cumulative_input = int(usage.get("input_tokens") or 0)
            self._cumulative_output = int(usage.get("output_tokens") or 0)
            self._cumulative_cache_hit = int(usage.get("cache_read_input_tokens") or 0)
            # last = cumulative（claude run 只有一次 final usage）
            self._last_input = self._cumulative_input
            self._last_output = self._cumulative_output
            self._last_cache_hit = self._cumulative_cache_hit

        if raw.get("ttft_ms") is not None:
            self._last_ttft_ms = int(raw["ttft_ms"])

    def _track_post_translate(self, ev: TranslatedEvent) -> None:
        """翻译后的 event 处理：累计 tool_calls 计数。"""
        if ev.type == "agent.tool_call":
            self.tool_calls.append({
                "tool_name": ev.payload.get("tool_name"),
                "tool_args": ev.payload.get("tool_args", {}),
                "tool_call_id": ev.payload.get("tool_call_id"),
            })

    def _emit(self, ev: TranslatedEvent) -> None:
        """emit 翻译事件到 bus；跳过生命周期事件（node_factory 自己 emit）。"""
        if ev.type in _LIFECYCLE_EVENTS_NOT_EMIT:
            return
        if self._bus is None:
            return
        # 翻译器 payload 已经包含 node_id / agent_name；额外补 workflow_id
        payload = dict(ev.payload)
        payload.setdefault("workflow_id", self._wid)
        safe_emit(self._bus, ev.type, payload)


# 显式协议契约校验：ClaudeCodeExecutor 实例必须满足 BaseExecutor
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
