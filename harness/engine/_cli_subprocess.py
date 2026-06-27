"""Generic CLI subprocess helper (P3-T2).

Profile-agnostic counterpart to ``harness/engine/_claude_subprocess.py``.
``run_cli`` spawns a CLI backend (claude / codex / opencode / user-defined)
described by a ``CliProfile``, streams stdout lines, drains stderr, and
returns a ``CliRunResult``. The profile dictates:

  - which binary to spawn (cli_path + flags)
  - how to deliver the prompt (stdin vs argv)
  - which env overlay to apply (env_overlay_prefixes from .env)
  - whether MCP is wired (mcp_flag_args rendered from profile template)

Behaviour parity with ``run_claude``:

  - SIGTERM on timeout, then SIGKILL after 10 s grace
  - stderr accumulated for diagnostic emit (caller wraps as ErrorEvent)
  - on_line callback never crashes the subprocess (errors logged + skipped)
  - cross-platform signal handling (ProcessLookupError tolerated)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
from typing import Awaitable, Callable

from harness.engine.cli_profile import CliProfile, CliRunResult, CliSpawnConfig

logger = logging.getLogger(__name__)


async def run_cli(
    cfg: CliSpawnConfig,
    profile: CliProfile,
    on_line: Callable[[str], Awaitable[None]] | None = None,
    *,
    timeout: float | None = None,
) -> CliRunResult:
    """Spawn the CLI backend described by ``profile``, stream stdout,
    drain stderr, and return a CliRunResult.

    Args:
        cfg: profile-agnostic spawn config (prompt + flags + env + paths).
        profile: the backend description — used only for logging context
            here (the cfg already encodes profile decisions).
        on_line: async callback invoked per stdout line (newline stripped).
            Errors in the callback are logged + skipped — never crash the
            subprocess over a translator/emit bug.
        timeout: wall-clock seconds; None = no limit. On timeout the
            subprocess gets SIGTERM, then SIGKILL after 10 s grace.

    Returns:
        CliRunResult with exit_code, accumulated stderr, timed_out flag.

    Raises:
        FileNotFoundError: when cfg.cli_path does not exist.
    """
    cmd = _build_cmd(cfg)
    logger.info("spawn %s: %s ...", profile.name, " ".join(cmd[:6]))
    logger.debug("full %s cmd: %s", profile.name, cmd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        cwd=cfg.cwd,
        env=_build_env(cfg.env_overlay),
    )

    # Deliver the prompt — stdin (claude-style) or argv (most others).
    # Argv-mode binaries ignore stdin so the write is harmless; we still
    # close stdin to signal "no more input" to stdin-mode binaries.
    assert proc.stdin is not None
    if cfg.prompt_channel == "stdin":
        proc.stdin.write(cfg.prompt.encode("utf-8"))
        await proc.stdin.drain()
    proc.stdin.close()
    await proc.stdin.wait_closed()

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
                    logger.exception(
                        "on_line callback failed; line was: %r", text[:200]
                    )

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
            "%s subprocess timed out after %ss; sending SIGTERM",
            profile.name, timeout,
        )
        _terminate_proc(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "%s did not exit 10s after SIGTERM; sending SIGKILL",
                profile.name,
            )
            _kill_proc(proc)
            await proc.wait()

    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    exit_code = proc.returncode if proc.returncode is not None else -1
    stderr_full = "".join(stderr_chunks)
    logger.info(
        "%s exited code=%s timed_out=%s stderr_bytes=%d",
        profile.name, exit_code, timed_out, len(stderr_full),
    )
    return CliRunResult(exit_code=exit_code, stderr=stderr_full, timed_out=timed_out)


def _build_cmd(cfg: CliSpawnConfig) -> list[str]:
    """Construct the argv. Prompt is delivered separately (stdin or argv).

    ``cfg.cli_path`` is split with ``shlex.split`` so a single token like
    ``"claude"`` stays as ``["claude"]`` while a wrapper invocation like
    ``"ccr code"`` expands to ``["ccr", "code"]``. ``create_subprocess_exec``
    does not invoke a shell, so multi-token cli_path must be split here.

    For argv-mode binaries, the prompt is appended as the last positional
    arg. Some CLIs (codex) expect this; others (claude) read stdin only.
    """
    cli_parts = shlex.split(cfg.cli_path) if cfg.cli_path else []
    cmd: list[str] = [*cli_parts, *cfg.flags]
    cmd.extend(cfg.mcp_flag_args)
    cmd.extend(cfg.extra_args)
    if cfg.prompt_channel == "argv":
        cmd.append(cfg.prompt)
    return cmd


def _build_env(env_overlay: dict[str, str] | None) -> dict[str, str]:
    """Merge current env + overlay. None = use current env verbatim."""
    base = dict(os.environ)
    if env_overlay:
        base.update(env_overlay)
    return base


def _terminate_proc(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.send_signal(signal.SIGTERM)
    except (ProcessLookupError, NotImplementedError):
        pass


def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except (ProcessLookupError, NotImplementedError):
        pass
