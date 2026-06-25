"""Claude Code subprocess helper（Phase C）。

封装 ``claude -p`` 子进程的 spawn / 流式读 / stdin prompt / 清理。
刻意与 ``ClaudeCodeExecutor`` 解耦——本模块只关心 stdio 字节流，不关心
事件翻译、结果提取、retry 等业务逻辑。

设计参考: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §6
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)


# Claude Code CLI 调用固定 flag 集（基于 Phase 1 V1-V5 验证）
DEFAULT_FLAGS: tuple[str, ...] = (
    "-p",
    "--dangerously-skip-permissions",  # 跳过权限提示（harness 已校验过）
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--verbose",
    "--strict-mcp-config",  # 只用 --mcp-config 提供的 server，忽略全局
)


@dataclass
class ClaudeSpawnConfig:
    """所有影响 ``claude`` 命令行参数的配置项。

    Phase C 只用 ``mcp_config_path`` 的能力，Phase D 起会真正指向 harness
    MCP server；本结构稳定，未来扩展不破坏 caller。
    """

    prompt: str
    mcp_config_path: Path | None = None
    allowed_tools: Sequence[str] | None = None  # None = claude 自选默认工具集
    session_id: str | None = None  # 用于 --session-id / --resume（Phase E）
    append_system_prompt: str | None = None  # agent MD 内容
    cwd: str | None = None
    env: dict[str, str] | None = None
    cli_path: str = "claude"  # 可被测试 monkeypatch
    extra_args: Sequence[str] = field(default_factory=tuple)


@dataclass
class ClaudeRunResult:
    """``run_claude`` 的返回值。"""

    exit_code: int
    stderr: str
    #: claude 调用超时（asyncio.wait_for 抛 TimeoutError）时 exit_code = -1
    timed_out: bool = False


async def run_claude(
    cfg: ClaudeSpawnConfig,
    on_line: Callable[[str], Awaitable[None]] | None = None,
    *,
    timeout: float | None = None,
) -> ClaudeRunResult:
    """spawn claude 子进程 + 流式读 stdout + 等退出。

    Args:
        cfg: 命令行构造配置
        on_line: 每读到一行 stdout 调一次（行已去掉结尾 newline）。
                 async callable，可以做翻译/emit 等任意操作。
                 如果为 None，stdout 仍正常消费但不触发回调。
        timeout: wall-clock 超时秒数；None 表示不限。超时触发 SIGTERM。

    Returns:
        ClaudeRunResult（exit_code + stderr 累计内容）

    Raises:
        FileNotFoundError: cli_path 不存在
    """
    cmd = _build_cmd(cfg)
    logger.info("spawn claude: %s", " ".join(cmd[:6]) + " ...")
    logger.debug("full claude cmd: %s", cmd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        cwd=cfg.cwd,
        env=_build_env(cfg.env),
    )

    # 写 prompt 到 stdin 然后关 stdin（claude -p 走 stdin 接 prompt）
    # 见 Phase 1 V1 教训：--allowed-tools variadic 会吞位置参数
    assert proc.stdin is not None
    proc.stdin.write(cfg.prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()
    await proc.stdin.wait_closed()

    # 并发：读 stdout 行 + 累计 stderr + 等退出
    stderr_chunks: list[str] = []
    timed_out = False

    async def _drain_stderr():
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

    async def _drain_stdout():
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if not text:
                continue
            if on_line is not None:
                try:
                    await on_line(text)
                except Exception:
                    # 翻译器/emit 出错不能让子进程挂掉——记录后继续
                    logger.exception("on_line callback failed; line was: %r", text[:200])

    stderr_task = asyncio.create_task(_drain_stderr())
    stdout_task = asyncio.create_task(_drain_stdout())

    try:
        if timeout is not None:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        else:
            await proc.wait()
    except asyncio.TimeoutError:
        timed_out = True
        logger.warning(
            "claude subprocess timed out after %ss; sending SIGTERM", timeout
        )
        _terminate_proc(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("claude did not exit 10s after SIGTERM; sending SIGKILL")
            _kill_proc(proc)
            await proc.wait()

    # 等 stdout/stderr drain 完成
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    exit_code = proc.returncode if proc.returncode is not None else -1
    stderr_full = "".join(stderr_chunks)
    logger.info(
        "claude exited code=%s timed_out=%s stderr_bytes=%d",
        exit_code, timed_out, len(stderr_full),
    )
    return ClaudeRunResult(exit_code=exit_code, stderr=stderr_full, timed_out=timed_out)


def _build_cmd(cfg: ClaudeSpawnConfig) -> list[str]:
    """构造 claude 命令行；prompt 走 stdin，不进 argv。"""
    cmd: list[str] = [cfg.cli_path, *DEFAULT_FLAGS]

    if cfg.mcp_config_path is not None:
        cmd.extend(["--mcp-config", str(cfg.mcp_config_path)])

    if cfg.allowed_tools:
        cmd.extend(["--allowed-tools", " ".join(cfg.allowed_tools)])

    if cfg.session_id is not None:
        cmd.extend(["--session-id", cfg.session_id])

    if cfg.append_system_prompt is not None:
        # 用文件而非 inline 避免长 prompt 撞 ARG_MAX
        # 调用方负责把内容写到临时文件，这里只接路径
        # 简化：直接用 inline flag（agent MD 一般 < 8KB）
        cmd.extend(["--append-system-prompt", cfg.append_system_prompt])

    if cfg.extra_args:
        cmd.extend(cfg.extra_args)

    return cmd


def _build_env(env_overlay: dict[str, str] | None) -> dict[str, str]:
    """合并当前 env + overlay。None 表示用当前 env。"""
    base = dict(os.environ)
    if env_overlay:
        base.update(env_overlay)
    return base


def _terminate_proc(proc: asyncio.subprocess.Process) -> None:
    """跨平台 SIGTERM。"""
    try:
        proc.send_signal(signal.SIGTERM)
    except (ProcessLookupError, NotImplementedError):
        pass


def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    """跨平台 SIGKILL。"""
    try:
        proc.kill()
    except (ProcessLookupError, NotImplementedError):
        pass
