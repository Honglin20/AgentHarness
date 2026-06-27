"""CCR (Claude Code Router) profile — minimal flags for old CCR versions.

Older CCR versions internally shell out to ``claude-code`` binary. If the
binary isn't installed, CCR falls back to direct API, but the fallback
doesn't support ``--mcp-config`` / ``--append-system-prompt`` / ``--dangerously-skip-permissions``.

This profile uses:
  - ``prompt_channel="argv"`` — prompt as positional arg (not stdin),
    matching the manual ``ccr code -p "prompt"`` invocation
  - No MCP support — old CCR fallback doesn't handle it
  - No claude-specific flags — only ``-p``

If you're on CCR v2.0.0+, prefer the builtin ``claude-code`` profile with
``HARNESS_CLAUDE_CLI=ccr code`` instead — it supports all flags natively.

Usage:
  1. Deploy to ``<project>/.harness/cli_profiles/ccr.py``
  2. Set workflow agent ``"executor": "ccr"``
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
    prompt_channel="argv",              # prompt 作为位置参数，不靠 stdin
    mcp_flag_template=None,             # 旧 CCR fallback 不支持 MCP
    env_overlay_prefixes=("ANTHROPIC_", "CLAUDE_"),
    translator=translate,
    result_extractor=extract_and_validate,
    stream_format="json",
)
