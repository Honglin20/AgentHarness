"""P3-T2: run_cli generic subprocess helper tests."""
from __future__ import annotations

import asyncio

import pytest

from harness.engine._cli_subprocess import _build_cmd, _build_env, run_cli
from harness.engine.cli_profile import (
    CliProfile,
    CliRunResult,
    CliSpawnConfig,
)


def _make_profile(name="test-cli", **overrides):
    defaults = dict(
        name=name,
        prompt_paradigm="minimal",
        cli_path_env="HARNESS_TEST_CLI",
        default_cli_path="test-cli",
        flags=("--foo",),
        prompt_channel="stdin",
        mcp_flag_template=None,
        env_overlay_prefixes=("TEST_",),
        translator=lambda r, c: [],
        result_extractor=lambda t, rt: t,
    )
    defaults.update(overrides)
    return CliProfile(**defaults)


# ---------------------------------------------------------------------------
# _build_cmd — argv construction
# ---------------------------------------------------------------------------


def test_build_cmd_stdin_channel_omits_prompt_from_argv():
    """stdin-mode binaries (claude) must NOT receive prompt as argv."""
    cfg = CliSpawnConfig(
        prompt="hello world", cli_path="test-cli",
        flags=("--foo", "--bar"), prompt_channel="stdin",
    )
    cmd = _build_cmd(cfg)
    assert cmd[0] == "test-cli"
    assert "--foo" in cmd and "--bar" in cmd
    assert "hello world" not in cmd


def test_build_cmd_argv_channel_appends_prompt():
    """argv-mode binaries (codex) receive prompt as the last positional."""
    cfg = CliSpawnConfig(
        prompt="do thing", cli_path="codex",
        flags=("--json",), prompt_channel="argv",
    )
    cmd = _build_cmd(cfg)
    assert cmd[-1] == "do thing"
    assert cmd[0] == "codex"


def test_build_cmd_mcp_flag_args_included_in_order():
    cfg = CliSpawnConfig(
        prompt="x", cli_path="cli", flags=("--a",),
        prompt_channel="stdin",
        mcp_flag_args=("--mcp-config", "/tmp/c.json"),
        extra_args=("--verbose",),
    )
    cmd = _build_cmd(cfg)
    # Order: cli_path + flags + mcp_flag_args + extra_args
    assert cmd == ["cli", "--a", "--mcp-config", "/tmp/c.json", "--verbose"]


# ---------------------------------------------------------------------------
# _build_env — env overlay merge
# ---------------------------------------------------------------------------


def test_build_env_none_overlay_returns_os_environ_copy():
    import os
    env = _build_env(None)
    assert env == dict(os.environ)


def test_build_env_overlay_merges_on_top():
    env = _build_env({"INJECTED_KEY": "value"})
    assert env["INJECTED_KEY"] == "value"


def test_build_env_overlay_overrides_existing():
    """Overlay wins over OS env (matters for ANTHROPIC_* redirection)."""
    env = _build_env({"PATH": "/custom"})
    assert env["PATH"] == "/custom"


# ---------------------------------------------------------------------------
# run_cli — full integration with mock subprocess
# ---------------------------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_run_cli_returns_exit_code_and_stderr(monkeypatch):
    """End-to-end mock: stub asyncio.create_subprocess_exec with a fake
    process that exits 0 + emits a stderr line."""

    class _FakeStdin:
        def __init__(self):
            self.written = b""
            self.closed = False
        def write(self, b):
            self.written += b
        async def drain(self):
            pass
        def close(self):
            self.closed = True
        async def wait_closed(self):
            pass

    class _FakeStream:
        def __init__(self, lines=None, stderr=None):
            self._lines = list(lines or [])
            self._stderr = stderr or b""
            self._read_called = False
        async def readline(self):
            if self._lines:
                line = self._lines.pop(0)
                return line.encode("utf-8")
            return b""
        async def read(self, n):
            if self._read_called:
                return b""
            self._read_called = True
            return self._stderr

    class _FakeProc:
        def __init__(self, exit_code, stdout_lines, stderr):
            self.stdin = _FakeStdin()
            self.stdout = _FakeStream(stdout_lines, stderr)
            self.stderr = _FakeStream(stderr=stderr)
            self._exit_code = exit_code
            self.returncode = None
            self._signals = []
        async def wait(self):
            self.returncode = self._exit_code
            return self._exit_code
        def send_signal(self, sig):
            self._signals.append(("term", sig))
        def kill(self):
            self._signals.append(("kill", None))

    captured_cfg = {}
    fake_proc = _FakeProc(
        exit_code=0,
        stdout_lines=['{"type":"result","is_error":false}'],
        stderr=b"some warning\n",
    )

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_cfg["cmd"] = args
        captured_cfg["env"] = kwargs.get("env")
        captured_cfg["cwd"] = kwargs.get("cwd")
        return fake_proc

    monkeypatch.setattr(
        "harness.engine._cli_subprocess.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    cfg = CliSpawnConfig(
        prompt="hello", cli_path="test-cli",
        flags=("--foo",), prompt_channel="stdin",
        env_overlay={"FOO": "bar"},
    )
    profile = _make_profile()
    result = _run(run_cli(cfg, profile, timeout=5.0))

    assert isinstance(result, CliRunResult)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "some warning" in result.stderr
    # stdin-mode: prompt written to stdin
    assert fake_proc.stdin.written == b"hello"
    assert fake_proc.stdin.closed is True
    # env overlay propagated
    assert captured_cfg["env"]["FOO"] == "bar"


def test_run_cli_calls_on_line_per_stdout_line(monkeypatch):
    """on_line callback fires once per non-empty stdout line."""
    received_lines = []

    class _FakeStdin:
        def write(self, b): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass

    class _FakeStream:
        def __init__(self, lines=None, stderr=b""):
            # Lines come in as str; convert each to "<line>\n" so empty
            # strings produce b"\n" (real-subprocess behavior) — distinct
            # from EOF which is b"".
            self._lines = [f"{ln}\n" for ln in (lines or [])]
            self._stderr = stderr
            self._read_called = False
        async def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0).encode("utf-8")
        async def read(self, n):
            if self._read_called: return b""
            self._read_called = True
            return self._stderr

    class _FakeProc:
        def __init__(self):
            self.stdin = _FakeStdin()
            self.stdout = _FakeStream(['line-1', '', 'line-2'])
            self.stderr = _FakeStream()
            self.returncode = 0
        async def wait(self):
            return 0
        def send_signal(self, s): pass
        def kill(self): pass

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(
        "harness.engine._cli_subprocess.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    async def on_line(line):
        received_lines.append(line)

    cfg = CliSpawnConfig(
        prompt="x", cli_path="cli", flags=(), prompt_channel="stdin",
    )
    profile = _make_profile()
    _run(run_cli(cfg, profile, on_line=on_line, timeout=5.0))

    # Empty line skipped; both non-empty lines received
    assert received_lines == ["line-1", "line-2"]


def test_run_cli_on_line_exception_does_not_crash_subprocess(monkeypatch):
    """A buggy on_line callback must NOT take down the subprocess — log
    + continue (matches run_claude behavior)."""
    class _FakeStdin:
        def write(self, b): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass

    class _FakeStream:
        def __init__(self, lines=None, stderr=b""):
            # Lines come in as str; convert each to "<line>\n" so empty
            # strings produce b"\n" (real-subprocess behavior) — distinct
            # from EOF which is b"".
            self._lines = [f"{ln}\n" for ln in (lines or [])]
            self._stderr = stderr
            self._read_called = False
        async def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0).encode("utf-8")
        async def read(self, n):
            if self._read_called: return b""
            self._read_called = True
            return self._stderr

    class _FakeProc:
        def __init__(self):
            self.stdin = _FakeStdin()
            self.stdout = _FakeStream(['good-1', 'good-2'])
            self.stderr = _FakeStream()
            self.returncode = 0
        async def wait(self):
            return 0
        def send_signal(self, s): pass
        def kill(self): pass

    async def fake_create_subprocess_exec_3(*a, **kw):
        return _FakeProc()

    monkeypatch.setattr(
        "harness.engine._cli_subprocess.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec_3,
    )

    received = []
    async def buggy_on_line(line):
        if line == "good-1":
            raise RuntimeError("buggy translator")
        received.append(line)

    cfg = CliSpawnConfig(prompt="x", cli_path="cli", flags=(), prompt_channel="stdin")
    result = _run(run_cli(cfg, _make_profile(), on_line=buggy_on_line, timeout=5.0))
    # Subprocess still exited 0 — buggy callback did not propagate
    assert result.exit_code == 0
    # Second line still processed despite first-line exception
    assert received == ["good-2"]
