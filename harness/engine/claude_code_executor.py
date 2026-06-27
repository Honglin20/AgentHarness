"""ClaudeCodeExecutor — per-node ``claude -p`` 子进程执行器（Phase C 实现）。

工作流：
  1. 构造 CliSpawnConfig（prompt + profile.flags + extra_args 含动态 flag）
  2. spawn claude 子进程（stdin 注入 prompt，由 profile.prompt_channel 决定）
  3. 流式读 stdout 行 → JSON parse → translate → emit 到 event_bus
  4. 等子进程退出；exit_code != 0 抛 RuntimeError
  5. 从最后一条 result 事件提取 ``result.result`` 字段
  6. 构造 duck-type AgentRunResult 返回（agent_run.result.output = 提取的内容）

接口与 LLMExecutor 完全平行（实现 BaseExecutor 协议），node_factory 不需要
知道是 pydantic-ai 还是 claude-code。

P3 补完：执行细节由 ``self._profile`` (CliProfile) 驱动——cli_path 来自
``profile.resolve_cli_path()``（支持 HARNESS_CLAUDE_CLI env override + shlex
多 token 如 "ccr code"），固定 flags 来自 profile.flags，MCP flag 由
profile.build_mcp_flag_args 渲染。``--setting-sources project`` 条件性追加：
仅当 env_overlay 非空时强制只读 project settings；否则让 claude fallback
到 ``~/.claude/settings.json`` 默认配置，避免缺 .env 时 API 错误。

Phase D 集成 harness MCP server（ping / ask_user / TodoTool / render_chart 桥接）：
  - run() 之前 _setup_mcp 启动 McpProxyServer + 写临时 mcp-config JSON
  - claude 通过 mcp-config 连 harness MCP server 子进程
  - tools/call 经 IPC 转发到主进程 handler
  - run() 之后 _teardown_mcp 清理 socket + 文件

Phase E 起会通过 session_id + --resume 支持 schema retry。

设计参考: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §6 §7
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from harness.engine.llm_executor import AgentRunResult, BaseExecutor
from harness.engine.token_aggregator import TokenAggregator
from harness.engine.tool_resolution import ToolResolution
from harness.engine._cli_subprocess import run_cli
from harness.engine._result_extractor import SchemaValidationError, extract_and_validate
from harness.engine.cli_profile import CliProfile, CliRunResult, CliSpawnConfig, get_profile
from harness.engine.error_event import ErrorEvent, ExecutorError
from harness.extensions.bus import safe_emit
from harness.types import AgentResult
from harness.translator import TranslateContext, TranslatedEvent, translate

logger = logging.getLogger(__name__)


# Claude 内置工具集 + lowercase 别名映射现在由 harness.cli_bridge_tools
# 统一管理（便于操作者编辑）。_resolve_allowed_tools / _rewrite_bare_tool_names
# 都从那里读 BRIDGED_TOOLS + LOWER_TO_CLAUDE_BUILTIN。


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

    P3-T4: profile-driven — cli path / flags / translator / extractor /
    prompt paradigm / MCP template all come from the CliProfile (default
    "claude-code" from harness/cli_profiles/claude.py). This makes the
    class reusable for any CLI backend that shares claude's stream-json
    output format — operators can override the profile to canary a
    different claude build or experiment with a fork.
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
        cli_path: str | None = None,
        timeout_s: float | None = None,
        mcp_config_path: Any | None = None,
        enable_mcp: bool = True,
        # P3-T4: profile override (None → registry lookup of "claude-code")
        profile: CliProfile | None = None,
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
        self._timeout_s = timeout_s
        # 显式传入的 mcp_config_path（一般用于测试 / 自定义 MCP）；
        # 为 None 且 enable_mcp=True 时 _setup_mcp 会自动生成。
        self._mcp_config_path = mcp_config_path
        self._enable_mcp = enable_mcp
        # P3-T4: profile-driven configuration. Resolve from registry if
        # caller didn't pass one (the production path via executor_factory
        # will pass get_profile("claude-code") explicitly once P3-T6 lands).
        # Lookup happens at __init__ so a missing builtin fails fast at
        # agent construction rather than mid-run.
        if profile is None:
            try:
                profile = get_profile("claude-code")
            except (KeyError, ValueError) as exc:
                raise RuntimeError(
                    f"ClaudeCodeExecutor requires 'claude-code' profile but "
                    f"registry lookup failed: {exc}. Ensure "
                    f"harness.cli_profiles is imported at startup."
                ) from exc
        self._profile = profile
        # P3 cli_path resolution: explicit kwarg wins; else profile.resolve_cli_path()
        # reads os.environ[profile.cli_path_env] with default profile.default_cli_path.
        # This honours HARNESS_CLAUDE_CLI override (single token "claude" or multi
        # token wrapper like "ccr code" — _cli_subprocess._build_cmd shlex.splits it).
        self._cli_path = cli_path if cli_path is not None else profile.resolve_cli_path()

        # ── Diagnostic: dump every relevant input to cli_path resolution ──
        _env_path = _resolve_env_path_for_diag()
        logger.warning(
            "[%s] __init__ cli_path resolution: "
            "explicit_kwarg=%r profile.cli_path_env=%r "
            "raw_os_environ=%r resolve_cli_path()=%r "
            "env_file=%s",
            profile.name,
            cli_path,
            profile.cli_path_env,
            os.environ.get(profile.cli_path_env, "(not set)"),
            self._cli_path,
            _env_path,
        )

        # Per-run MCP state（_setup_mcp 创建，_teardown_mcp 清理）
        self._proxy: Any | None = None  # McpProxyServer，避免顶层循环 import
        self._mcp_config_file: Path | None = None
        self._mcp_serve_task: asyncio.Task | None = None

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
        # P2-T3: stream-side error state. Translator no longer emits
        # node.failed for result.is_error=true (P2-T4) — the executor owns
        # the emit. These fields capture the failure context for run() to
        # construct a phase="stream" ErrorEvent after claude exits.
        self._stream_error_seen: bool = False
        self._stream_error_meta: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API — BaseExecutor 协议
    # ------------------------------------------------------------------

    async def run(self, context: str) -> AgentRunResult:
        """spawn claude, stream-translate-emit, 返回 duck-type AgentRunResult。

        Raises:
            ExecutorError: claude 子进程 exit_code != 0 / 超时 / 无 result /
                schema 校验失败 / stream indicated is_error. Executor 已经
                emit ``agent.executor_error`` 到 bus；node_factory / retry
                层见 ExecutorError 不应重 emit（详见 error_event.py 契约）。
        """
        # 重置 per-run state（万一同一实例被重试逻辑复用）
        self._reset_run_state()
        t0 = time.time()

        # Phase D: 按需启动 harness MCP server，写 mcp-config，让 claude 能调
        # 前端联动工具（ask_user 等）。enable_mcp=False 跳过（CI 单测常用）。
        mcp_config_path = self._mcp_config_path
        if mcp_config_path is None and self._enable_mcp:
            t_mcp_start = time.monotonic()
            mcp_config_path = await self._setup_mcp()
            logger.warning(
                "[%s] _setup_mcp completed in %.2fs (mcp_config_path=%s)",
                self._profile.name, time.monotonic() - t_mcp_start, mcp_config_path,
            )
        else:
            logger.warning(
                "[%s] MCP disabled (enable_mcp=%s, mcp_config_path=%s)",
                self._profile.name, self._enable_mcp, self._mcp_config_path,
            )

        try:
            # claude -p requires non-empty stdin. When context is empty (no
            # inputs, no upstream), provide a minimal default user message.
            if not context.strip():
                context = "Proceed with the task as described in your instructions."
            cfg = self._build_spawn_config(context, mcp_config_path)
            logger.warning(
                "[%s] spawn config: cli_path=%r flags=%d items extra_args=%d items mcp_flag_args=%d items",
                self._profile.name, cfg.cli_path,
                len(cfg.flags), len(cfg.extra_args), len(cfg.mcp_flag_args),
            )
            ctx = self._build_translate_ctx()

            # 把 stdout 每行喂翻译器，再 emit
            async def on_line(line: str) -> None:
                await self._handle_stdout_line(line, ctx)

            # check_interrupt 钩子：让 WS 中断能取消 claude 子进程
            # 当前实现：spawn 期间不主动 check（pydantic-ai 路径在 iter 中 check）；
            # Phase G 加精细 cancel 支持

            cli_result = await run_cli(cfg, profile=self._profile, on_line=on_line, timeout=self._timeout_s)

            # Phase 2-T3: 统一错误封装 — 每个 phase 失败都 emit agent.executor_error
            # (critical, P2-T2) + raise ExecutorError. node_factory except 见
            # ExecutorError 走 retry 路径但不重 emit (emit-uniqueness 契约).
            if cli_result.timed_out:
                await self._emit_and_raise_executor_error(
                    phase="timeout",
                    error_type="ClaudeTimeout",
                    error_message=(
                        f"claude subprocess timed out after {self._timeout_s}s; "
                        f"terminated via SIGTERM/SIGKILL"
                    ),
                    stderr_tail=cli_result.stderr[-500:] or None,
                    exit_code=cli_result.exit_code,
                    timed_out=True,
                )

            if cli_result.exit_code != 0:
                await self._emit_and_raise_executor_error(
                    phase="spawn",
                    error_type="ClaudeSubprocessExit",
                    error_message=(
                        f"claude subprocess exited code={cli_result.exit_code}"
                    ),
                    stderr_tail=cli_result.stderr[-500:] or None,
                    exit_code=cli_result.exit_code,
                )

            # stream indicated is_error (translator saw result.is_error=true;
            # executor flagged via _extract_pre_translate). Translator no
            # longer emits node.failed for this case (P2-T4) — executor owns it.
            if self._stream_error_seen:
                # Compose a helpful message from captured meta: prefer the
                # claude-side error description, fall back to api_error_status.
                api_status = self._stream_error_meta.get("api_error_status")
                api_result = self._stream_error_meta.get("api_error_result")
                if api_result:
                    msg = f"claude stream failed: {api_result}"
                elif api_status is not None:
                    msg = f"claude stream failed (api_error_status={api_status})"
                else:
                    msg = "claude stream-json emitted result with is_error=true"
                await self._emit_and_raise_executor_error(
                    phase="stream",
                    error_type="ClaudeStreamError",
                    error_message=msg,
                    stderr_tail=cli_result.stderr[-500:] or None,
                    exit_code=cli_result.exit_code,
                    extra=self._stream_error_meta,
                )

            # result_text 为空说明 claude 没产出 result 事件（异常情况）
            if self._final_result_text is None:
                await self._emit_and_raise_executor_error(
                    phase="result_parse",
                    error_type="ClaudeNoResultEvent",
                    error_message=(
                        "claude exited 0 but emitted no result event"
                    ),
                    stderr_tail=cli_result.stderr[-500:] or None,
                    exit_code=cli_result.exit_code,
                )
        finally:
            # cleanup MCP（即使是失败路径也要清理 socket + 文件）
            if self._enable_mcp and self._mcp_config_path is None:
                await self._teardown_mcp()

        # Phase E: 提取 + schema 校验. SchemaValidationError → wrap as
        # ExecutorError(schema_validate) so execute_with_retry drives the
        # retry uniformly. emit before raise so frontend sees the failure.
        try:
            validated_output = self._extract_and_validate_result(self._final_result_text)
        except SchemaValidationError as e:
            await self._emit_and_raise_executor_error(
                phase="schema_validate",
                error_type=type(e).__name__,
                error_message=str(e),
                stderr_tail=None,
                exit_code=0,
                extra={"raw_result_text_len": len(self._final_result_text or "")},
            )
            return  # unreachable (_emit_and_raise_executor_error raises)

        usage = _ClaudeUsage(
            input_tokens=self._cumulative_input,
            output_tokens=self._cumulative_output,
            cache_read_tokens=self._cumulative_cache_hit,
            requests=1,
            tool_calls=len(self.tool_calls),
        )
        agent_run = _ClaudeAgentRun(
            result=_ClaudeResult(output=validated_output),
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
        self._stream_error_seen = False
        self._stream_error_meta = {}

    async def _emit_and_raise_executor_error(
        self,
        *,
        phase: str,
        error_type: str,
        error_message: str,
        stderr_tail: str | None,
        exit_code: int | None,
        timed_out: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Construct ErrorEvent → emit agent.executor_error (critical) → raise.

        Single emit point per ADR Decision 2 invariant. Always raises
        ExecutorError; the only caller that does not propagate is the
        schema_validate path (it returns after the call for type-checker
        peace of mind, but the raise makes it unreachable).
        """
        event = ErrorEvent(
            workflow_id=self._wid,
            node_id=self._node_id,
            agent_name=self._agent_name,
            executor=self._profile.name,
            phase=phase,
            error_type=error_type,
            error_message=error_message,
            stderr_tail=stderr_tail,
            exit_code=exit_code,
            timed_out=timed_out,
            extra=extra or {},
        )
        if self._bus is not None:
            safe_emit(self._bus, "agent.executor_error", event.to_payload())
        raise ExecutorError(error_message, event)

    def _build_spawn_config(
        self, context: str, mcp_config_path: Any | None = None
    ) -> CliSpawnConfig:
        """从 agent_def + context 构造 spawn 配置。

        P3 补完：返回 profile-agnostic ``CliSpawnConfig``。所有 claude-specific
        动态 flag（``--allowed-tools`` / ``--append-system-prompt`` / 条件性
        ``--setting-sources project``）拼到 ``extra_args``，由
        ``_cli_subprocess._build_cmd`` 透传给最终 argv。固定 flags 来自
        ``self._profile.flags``，MCP flag 由 ``profile.build_mcp_flag_args`` 渲染。

        mcp_config_path 显式传入时优先；None 时 fallback 到 self._mcp_config_path
        （用于测试 / 自定义场景，run() 主流程会通过 _setup_mcp 生成并显式传入）。
        """
        # system prompt: agent MD 内容（deps 应提供）
        system_prompt = self._resolve_system_prompt()

        allowed_tools = self._resolve_allowed_tools()

        # Bare 工具名重写：BRIDGED_TOOLS 里的工具在 claude 子进程里暴露为
        # mcp__harness__<name>，但 agent MD 通常按字面写 "ask_user"。
        # 旧路径（_inject_tool_name_mapping）在 prompt 末尾追加 mapping 段，
        # 同时提及 bare 和 mcp__ 两个名字 → 模型同时尝试两者 → 重复调用
        # （run bc2f394c：greeter 3 次 / survey 2 次）。
        # 改为 in-place 文本替换：prompt 里只剩 mcp__ 全名，从源头消除歧义。
        system_prompt = self._rewrite_bare_tool_names(system_prompt)

        # 显式 > self._mcp_config_path（兼容旧测试 + 自定义注入）
        effective_mcp = mcp_config_path if mcp_config_path is not None else self._mcp_config_path

        # 项目 .env overlay：让 claude -p 子进程用项目级 LLM 配置，而不是
        # 父进程（harness server 启动 shell）继承的全局 env。这样 claude code
        # 编程环境的 ANTHROPIC_* 不会污染 spawn 的 claude -p 子进程；项目 .env
        # 里的 ANTHROPIC_* 优先级最高。
        env_overlay = self._load_env_overlay()

        # claude -p requires non-empty stdin — fallback when context is empty
        # (e.g. first node with no inputs or upstream outputs).
        prompt = context if context else "Complete the task described in the system prompt."

        # claude-specific 动态 flag → extra_args（_cli_subprocess._build_cmd 透传）
        extra_args: list[str] = []
        if allowed_tools:
            # 空格 join 单 flag 传递：variadic 形式会吞位置参数（Phase 1 V1 教训）
            extra_args.extend(["--allowed-tools", " ".join(allowed_tools)])
        if system_prompt:
            extra_args.extend(["--append-system-prompt", system_prompt])

        # 条件性 --setting-sources project：仅当 .env 提供了 profile 前缀的 key
        # （env_overlay 非空）时强制 claude -p 只读 project settings（隔离 shell
        # 全局 env 污染）。.env 缺失时不加，让 claude fallback 到
        # ~/.claude/settings.json + shell env 默认配置，避免 API 错误。
        if env_overlay:
            extra_args.extend(["--setting-sources", "project"])

        cfg = CliSpawnConfig(
            prompt=prompt,
            cli_path=self._cli_path,
            flags=self._profile.flags,
            prompt_channel=self._profile.prompt_channel,
            env_overlay=env_overlay,
            mcp_flag_args=self._profile.build_mcp_flag_args(
                str(effective_mcp) if effective_mcp else None
            ),
            extra_args=tuple(extra_args),
        )
        return cfg

    def _load_env_overlay(self) -> dict[str, str]:
        """读项目 .env，按 profile.env_overlay_prefixes 提取 keys 作为
        子进程 env overlay。同时支持 ``HARNESS_<NAME>_ENV_<KEY>`` 形式
        覆盖单个 env var。

        注意：本函数**只负责 env var 透传**。cli_path 的覆盖走另一条路：
        ``profile.resolve_cli_path()`` 读 ``os.environ[profile.cli_path_env]``
        （claude profile 即 ``HARNESS_CLAUDE_CLI``），在 ``__init__`` 里调用。
        env_overlay 是否非空还驱动 ``--setting-sources project`` 条件性追加
        （见 ``_build_spawn_config``）。

        P3-T7: prefixes 来自 ``self._profile.env_overlay_prefixes``（claude
        profile 是 ("ANTHROPIC_", "CLAUDE_")，opencode 可能是 ("OPENCODE_",)）。
        以前硬编码 ANTHROPIC_/CLAUDE_ — 现在通过 profile 配置，新 backend
        不需要改 executor 代码。

        查找顺序：``harness.paths.get_env_file()``（项目根 .env）。
        只提取 profile 声明的前缀，避免把整个 .env（可能含敏感
        HARNESS_API_KEY 等）带进子进程；HARNESS_* 已经在父进程 env 里，
        子进程天然继承。

        为什么需要：用户用 claude code 编程时，shell 全局 env 里的
        ANTHROPIC_AUTH_TOKEN/BASE_URL 指向编程用的 gateway。如果 spawn
        的 claude -p 直接继承，会走同一个 gateway（可能限流 / 不是项目
        想用的）。项目 .env 提供独立配置，让子进程走项目指定的 gateway。

        为什么用 ``get_env_file()`` 而不是 ``Path.cwd()/.env``：``runner.run``
        会 ``os.chdir(work_dir)`` 让 agent 在工作目录运行，cwd 此刻指向
        work_dir（通常没有 .env），会导致 overlay 返回空 dict、子进程回退到
        继承父进程 env（被 shell 的 ANTHROPIC_* 污染）。``get_env_file()``
        通过 HARNESS_PROJECT_ROOT / CWD heuristic / package parent 三层
        fallback 稳定定位到项目根 .env，不受 chdir 影响。
        """
        from harness.paths import get_env_file
        import os
        overlay: dict[str, str] = {}
        env_path = get_env_file()
        prefixes = tuple(self._profile.env_overlay_prefixes)
        # Construct the per-profile env override prefix:
        #   claude-code → HARNESS_CLAUDE_CODE_ENV_
        # Profile names use kebab-case; convert to upper-snake for env vars.
        profile_env_prefix = "HARNESS_" + self._profile.name.upper().replace("-", "_") + "_ENV_"
        if env_path.exists():
            try:
                content = env_path.read_text(encoding="utf-8")
            except OSError:
                content = ""
            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                # Only overlay profile-declared prefixes; other env vars
                # are inherited from the parent process naturally.
                if key.startswith(prefixes):
                    overlay[key] = value
        # Layer 2: per-profile HARNESS_<NAME>_ENV_<KEY>=val overrides win
        # over .env values. Lets operators do canary tests without editing
        # the project .env (e.g. HARNESS_CLAUDE_CODE_ENV_ANTHROPIC_BASE_URL=...).
        for env_key, env_value in os.environ.items():
            if env_key.startswith(profile_env_prefix):
                stripped = env_key[len(profile_env_prefix):]
                overlay[stripped] = env_value
        if overlay:
            logger.debug(
                "%s env overlay: keys=%s",
                self._profile.name, sorted(overlay.keys()),
            )
        return overlay

    # ------------------------------------------------------------------
    # MCP setup / teardown (Phase D)
    # ------------------------------------------------------------------

    async def _setup_mcp(self) -> Path:
        """启动 McpProxyServer + 写 mcp-config JSON 文件，返回 path。

        claude 通过 ``--mcp-config <path>`` 连接，文件指向 harness.mcp.server
        子进程，env 含 socket path 让子进程找到主进程。
        """
        # 局部 import 避免顶层依赖循环（harness.mcp.proxy import ask_user 间接拉工具链）
        from harness.mcp.proxy import (
            HandlerCtx,
            McpProxyServer,
            register_default_handlers,
        )
        from harness.mcp.server import SOCKET_PATH_ENV

        # 注册内置 handler（idempotent：register_handler 同名覆盖）
        register_default_handlers()

        # 启动 proxy
        proxy_ctx = HandlerCtx(
            workflow_id=self._wid,
            node_id=self._node_id,
            agent_name=self._agent_name,
            event_bus=self._bus,
        )
        self._proxy = McpProxyServer(ctx=proxy_ctx)
        socket_path = await self._proxy.start()
        self._mcp_serve_task = asyncio.create_task(self._proxy.serve_until_stopped())

        # 写 mcp-config JSON（claude --mcp-config <path>）
        # 重要：claude 子进程的 cwd 是 workflow 的 work_dir（runner.run 调
        # os.chdir(work_dir) 让 agent 在工作目录跑），claude 通过 mcp-config
        # spawn MCP server 子进程时会继承这个 cwd。``python -m harness.mcp.server``
        # 需要能 import harness 包，但 work_dir 没有 harness/，所以必须通过
        # PYTHONPATH 指向项目根，否则 MCP server 启动时 ModuleNotFoundError →
        # claude 标记 ``mcp_servers[].status = "failed"`` → 工具全部不可用。
        from harness.paths import get_project_root
        project_root = str(get_project_root())
        cfg = {
            "mcpServers": {
                "harness": {
                    "command": sys.executable,
                    "args": ["-m", "harness.mcp.server"],
                    "env": {
                        SOCKET_PATH_ENV: socket_path,
                        "PYTHONPATH": project_root,
                    },
                }
            }
        }
        # 临时文件，关闭后保留（claude 子进程读）；run() 结束时 _teardown_mcp 删
        f = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="harness-mcp-config-",
            delete=False,
            dir=tempfile.gettempdir(),
        )
        json.dump(cfg, f, indent=2)
        f.close()
        self._mcp_config_file = Path(f.name)
        logger.info(
            "ClaudeCodeExecutor MCP setup: socket=%s config=%s",
            socket_path, self._mcp_config_file,
        )
        return self._mcp_config_file

    async def _teardown_mcp(self) -> None:
        """清理：cancel serve task + stop proxy + 删 mcp-config 文件。"""
        if self._mcp_serve_task is not None:
            self._mcp_serve_task.cancel()
            try:
                await asyncio.gather(self._mcp_serve_task, return_exceptions=True)
            except Exception:
                pass
            self._mcp_serve_task = None

        if self._proxy is not None:
            try:
                await self._proxy.stop()
            except Exception:
                logger.exception("MCP proxy stop failed")
            self._proxy = None

        if self._mcp_config_file is not None:
            try:
                self._mcp_config_file.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("failed to remove mcp config %s", self._mcp_config_file)
            self._mcp_config_file = None

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
        """从 agent_def.tools 提取白名单；None = claude 自选。

        Resolution 走 ``harness.cli_bridge_tools.resolve_for_claude``：
          - 在 BRIDGED_TOOLS 里 → ``mcp__harness__<name>``（harness MCP 桥接）
          - lowercase 别名（bash/grep/...） → Claude built-in canonical（``Bash``）
          - 显式 ``mcp__*`` / 大写 built-in → 原样透传

        详见 ``harness/cli_bridge_tools.py`` 模块 docstring。
        """
        from harness.cli_bridge_tools import resolve_for_claude

        if self.agent_def is None:
            return None
        tools = getattr(self.agent_def, "tools", None)
        if not tools:
            return None
        return [resolve_for_claude(t) for t in tools]

    def resolve_tools(self) -> list[ToolResolution]:
        """claude-code backend resolution. See ``resolve_tools_for_backend``."""
        from harness.engine.tool_resolution import resolve_tools_for_backend

        if self.agent_def is None:
            return []
        tools = getattr(self.agent_def, "tools", None) or []
        return resolve_tools_for_backend(tools, "claude-code")

    def _rewrite_bare_tool_names(self, system_prompt: str | None) -> str | None:
        """把 agent MD 里的 bare 工具名替换成 MCP 全名（in-place）。

        BRIDGED_TOOLS 里的工具在 claude 子进程里暴露为 ``mcp__harness__<name>``。
        agent MD 通常按字面引用（"call `ask_user`"），不替换会让模型按字面
        调 bare 名字 → claude 报 "No such tool"。

        旧路径 ``_inject_tool_name_mapping`` 在 prompt 末尾追加 mapping 段，
        同时提及 bare 和 mcp__ 两个名字 → 模型同时尝试两者 → 重复调用
        （run bc2f394c：greeter 3 次 / survey 2 次，见 ADR）。

        本方法做 in-place 文本替换：prompt 里只剩 ``mcp__harness__<name>`` 一个
        引用，从源头消除歧义。用 negative lookbehind/lookahead 匹配独立 token，
        避免误伤子串（如 ``ask_user_count``）。

        非 BRIDGED_TOOLS（bash/grep/...）不替换——它们已映射到 Claude built-in，
        prompt 字面与 claude 看到的工具名一致。
        """
        import re
        from harness.cli_bridge_tools import BRIDGED_TOOLS

        if self.agent_def is None or not system_prompt:
            return system_prompt
        tools = getattr(self.agent_def, "tools", None) or []
        bridged = [t for t in tools if t in BRIDGED_TOOLS]
        if not bridged:
            return system_prompt
        result = system_prompt
        for t in bridged:
            full_name = f"mcp__harness__{t}"
            # 独立 token：前后非字母数字下划线
            pattern = rf"(?<![a-zA-Z0-9_]){re.escape(t)}(?![a-zA-Z0-9_])"
            result = re.sub(pattern, full_name, result)
        return result

    def _extract_and_validate_result(self, text: str):
        """Phase E: 从 claude result.text 提取 + schema 校验。

        策略:
          - result_type is None / AgentResult（默认）: 容忍纯文本，
            包成 AgentResult(summary=text) 返回
          - result_type 是自定义 BaseModel: 严格 JSON 提取 + pydantic 校验，
            失败抛 SchemaValidationError

        SchemaValidationError 由 execute_with_retry 接管重试（与 pydantic-ai 路径
        的 ModelRetry 语义平行）。Phase E.2 会加 --resume + feedback 注入，
        让重试带上 schema 错误信息回喂 claude。
        """
        if self.agent_def is None:
            return text

        result_type = getattr(self.agent_def, "result_type", None)
        if result_type is None or result_type is AgentResult:
            # 默认 result_type：把 text 作为 summary（pydantic-ai 路径也类似）
            return AgentResult(summary=text)

        # 自定义 result_type：严格 JSON 提取 + 校验
        # P3-T4: delegate to profile.result_extractor (claude profile
        # delegates to _result_extractor.extract_and_validate).
        return self._profile.result_extractor(text, result_type)

    def _build_translate_ctx(self) -> TranslateContext:
        return TranslateContext(
            node_id=self._node_id,
            agent_name=self._agent_name,
            iteration=1,  # Phase G 加精细 iteration tracking
            attempt=1,
        )

    async def _handle_stdout_line(self, line: str, ctx: TranslateContext) -> None:
        """每行 stdout: json parse → translate → emit + 抽取 usage/result/tool_calls。

        stream_format="text" 时跳过 JSON parse，直接累积文本 + emit text_delta。
        """
        if self._profile.stream_format == "text":
            if self._final_result_text is None:
                self._final_result_text = line
            else:
                self._final_result_text += "\n" + line
            self._emit(TranslatedEvent(
                type="agent.text_delta",
                payload={"node_id": ctx.node_id, "agent_name": ctx.agent_name,
                         "text": line, "partial": True},
            ))
            return

        # JSON mode: existing behavior
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

        # P2-T3: 检测 result.is_error 并捕获上下文。翻译器（P2-T4）不再 emit
        # node.failed for this case — executor 在 run() 主循环里统一 emit
        # phase="stream" 错误事件。
        if raw.get("is_error"):
            self._stream_error_seen = True
            api_error_status = raw.get("api_error_status")
            if api_error_status is not None:
                self._stream_error_meta["api_error_status"] = api_error_status
            # result.result 在 is_error 时通常含 claude 的错误描述
            # (e.g. "rate limited" / "context overflow"). 保留供 emit 时
            # 拼到 error_message，让前端不用看 stderr 就能定位原因。
            error_result = raw.get("result")
            if isinstance(error_result, str) and error_result.strip():
                self._stream_error_meta["api_error_result"] = error_result.strip()[:500]

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


def _resolve_env_path_for_diag() -> str:
    """Resolve env file path for diagnostic logging — mirrors harness.config logic."""
    from harness.paths import get_env_file
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return str(cwd_env)
    env_file = get_env_file()
    return str(env_file) if env_file.exists() else f"(not found; cwd={Path.cwd()})"


# 显式协议契约校验：ClaudeCodeExecutor 实例必须满足 BaseExecutor。
# P3-T4: pass a minimal mock profile so the check does not depend on the
# profile registry being pre-loaded (import-time check must work even
# before harness.cli_profiles is imported).
def _build_check_profile() -> CliProfile:
    return CliProfile(
        name="claude-code",
        prompt_paradigm="minimal",
        cli_path_env="HARNESS_CLAUDE_CLI",
        default_cli_path="claude",
        flags=(),
        prompt_channel="stdin",
        mcp_flag_template=None,
        env_overlay_prefixes=("ANTHROPIC_",),
        translator=lambda r, c: [],
        result_extractor=lambda t, rt: t,
    )


_BASE_EXECUTOR_CHECK = isinstance(
    ClaudeCodeExecutor(
        agent_def=None, deps=None, workflow_id="x", node_id="x", agent_name="x",
        profile=_build_check_profile(),
    ),
    BaseExecutor,
)
assert _BASE_EXECUTOR_CHECK, (
    "ClaudeCodeExecutor must satisfy BaseExecutor protocol — "
    "missing run/record_usage/get_last_request_usage/tool_calls"
)
