"""Builtin CliProfile for the claude-code backend (P3-T3).

Single source of truth for "claude-code" executor configuration:
  - flags migrated from harness/engine/_claude_subprocess.py:DEFAULT_FLAGS
  - translator delegates to harness.translator.stream_json.translate
  - result_extractor delegates to harness.engine._result_extractor.extract_and_validate
  - prompt_paradigm = "minimal" (P1 base_minimal.md + minimal output format)
  - MCP support via --mcp-config flag

Loading: harness/cli_profiles/__init__.py auto-discovers this module
on import and registers the PROFILE.
"""
from __future__ import annotations

from harness.engine._result_extractor import extract_and_validate
from harness.engine.cli_profile import CliProfile
from harness.translator import translate as _claude_translator


#: Claude Code CLI invocation flags. Migrated verbatim from the pre-P3
#: ``harness/engine/_claude_subprocess.py:DEFAULT_FLAGS`` so existing
#: behaviour is preserved byte-level.
#:
#: Adding / removing flags here changes every claude -p spawn — bump the
#: ADR + add a release-note entry.
CLAUDE_FLAGS: tuple[str, ...] = (
    "-p",
    "--dangerously-skip-permissions",  # harness has already validated the workflow
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--verbose",
    "--strict-mcp-config",  # only use servers from --mcp-config, ignore global
    # Skip user-level ~/.claude/settings.json env field (may hardcode a
    # different gateway). Only load project-level settings so subprocess
    # env is fully controlled by the project's .env.
    "--setting-sources", "project",
)


PROFILE = CliProfile(
    name="claude-code",
    prompt_paradigm="minimal",
    cli_path_env="HARNESS_CLAUDE_CLI",
    default_cli_path="claude",
    flags=CLAUDE_FLAGS,
    prompt_channel="stdin",
    mcp_flag_template="--mcp-config {path}",
    env_overlay_prefixes=("ANTHROPIC_", "CLAUDE_"),
    translator=_claude_translator,
    result_extractor=extract_and_validate,
    # No default timeout — let the caller (ClaudeCodeExecutor) decide
    # based on agent_def / workflow config. Claude -p can run for
    # minutes on legitimate long tasks.
    default_timeout_s=None,
)
