"""CCR (Claude Code Router) profile — Claude Code drop-in replacement.

CCR v2.0.0+ supports the same flags as claude (``--output-format stream-json``,
``--append-system-prompt``, ``--mcp-config``, etc.). The prompt is delivered
via stdin (same as claude) because ``--append-system-prompt`` (appended by
the executor) requires stdin mode.

Usage:
  1. Set workflow agent ``"executor": "ccr"``
  2. Optionally set ``HARNESS_CCR_CLI`` env var to override ``ccr code`` path
  3. Ensure CCR is configured (``~/.claude-code-router/config.json``)
"""
from __future__ import annotations

from harness.engine._result_extractor import extract_and_validate
from harness.engine.cli_profile import CliProfile
from harness.translator import translate


PROFILE = CliProfile(
    name="ccr",
    prompt_paradigm="minimal",
    cli_path_env="HARNESS_CCR_CLI",
    default_cli_path="ccr code",
    flags=("-p",),
    prompt_channel="stdin",
    mcp_flag_template=None,
    env_overlay_prefixes=("ANTHROPIC_", "CLAUDE_"),
    translator=translate,
    result_extractor=extract_and_validate,
    stream_format="json",
)
