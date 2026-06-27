"""CliProfile — declarative description of a CLI subprocess backend (P3-T1).

A ``CliProfile`` captures everything the generic ``CliExecutorBase`` needs
to know about a specific CLI tool (claude / codex / opencode / user-defined):

  - which prompt paradigm it follows (pydantic-ai / minimal — informs the
    prompt assembler; see harness/prompts/assembler.py)
  - how to find the binary (env override + default path)
  - which fixed flags to pass (e.g. --output-format stream-json for claude)
  - how the prompt is delivered to the binary (stdin vs argv)
  - whether the binary supports MCP and via which flag template
  - which env var prefixes to overlay from .env (ANTHROPIC_ / OPENCODE_ / ...)
  - which translator parses the binary's stream output
  - which result extractor pulls the structured output from the final text

Profiles are registered via ``harness/cli_profiles/__init__.py`` (builtins)
or discovered from ``<cwd>/.harness/cli_profiles/<name>.py`` (project-level,
last-write-wins over builtins). See ADR Decision 3 for the persistence
contract (mirrors harness/config.py:15-20 .env fallback).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Type

from pydantic import BaseModel

from harness.translator import TranslateContext, TranslatedEvent


#: Prompt paradigm membership — must match harness/prompts/assembler.py.
PromptParadigm = Literal["pydantic-ai", "minimal"]


#: How the prompt reaches the CLI binary.
PromptChannel = Literal["stdin", "argv"]


#: Output stream format — controls how the executor parses stdout lines.
#: ``"json"`` = stream-json (one JSON object per line, claude / codex / opencode).
#: ``"text"`` = plain text lines accumulated as-is (minimal wrappers like ``ccr``).
StreamFormat = Literal["json", "text"]


@dataclass
class CliSpawnConfig:
    """Generic spawn config produced by CliExecutorBase + consumed by run_cli.

    Profile-agnostic: the same struct works for claude / opencode / codex /
    user-defined backends. Profile-specific flags go via ``extra_args``.
    """
    prompt: str
    cli_path: str
    flags: tuple[str, ...]
    prompt_channel: PromptChannel
    env_overlay: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    mcp_flag_args: tuple[str, ...] = field(default_factory=tuple)
    extra_args: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class CliRunResult:
    """Outcome of a CLI subprocess run.

    ``exit_code`` is -1 when the subprocess never returned a code (e.g.
    cancelled before spawn completed). ``timed_out`` is distinct from
    ``exit_code`` so callers can disambiguate timeout-SIGTERM-from-us vs
    exit-from-cli.
    """
    exit_code: int
    stderr: str
    timed_out: bool = False


#: Translator signature — same as harness.translator.translate.
Translator = Callable[[dict, TranslateContext], list[TranslatedEvent]]


#: Result extractor signature — pulls the structured output from the
#: final text the CLI emitted. Raises SchemaValidationError on failure
#: (caller — CliExecutorBase — wraps as ExecutorError).
ResultExtractor = Callable[[str, Type[BaseModel] | None], Any]


#: MCP config-builder signature — produces the dict that gets written to
#: the temp mcp-config JSON file. Returns None to disable MCP for this
#: profile. Default impl writes a harness-style config; profiles override
#: when the binary's MCP schema differs.
McpConfigBuilder = Callable[[str, str], dict | None]


@dataclass
class CliProfile:
    """Declarative description of a CLI subprocess backend.

    Field semantics — see ADR Decision 3 for full rationale:

      name                : canonical executor name ("claude-code" etc.)
      prompt_paradigm     : which base.md + output format to use
      cli_path_env        : env var name overriding cli_path
                            (e.g. "HARNESS_CLAUDE_CLI")
      default_cli_path    : default binary name ("claude")
      flags               : fixed flags every invocation passes
      prompt_channel      : "stdin" (claude) or "argv" (most others)
      mcp_flag_template   : format string for the MCP-config flag, e.g.
                            "--mcp-config {path}"; None = no MCP support
      env_overlay_prefixes: tuple of .env key prefixes this profile
                            extracts (e.g. ("ANTHROPIC_", "CLAUDE_"))
      translator          : function translating the binary's stream
                            output to harness events
      result_extractor    : function pulling structured output from
                            final text
      default_timeout_s   : per-invocation wall-clock timeout (None = no
                            limit; CLI backends should set a sane default
                            because users cannot Ctrl+C a runaway LLM)
    """
    name: str
    prompt_paradigm: PromptParadigm
    cli_path_env: str
    default_cli_path: str
    flags: tuple[str, ...]
    prompt_channel: PromptChannel
    mcp_flag_template: str | None
    env_overlay_prefixes: tuple[str, ...]
    translator: Translator
    result_extractor: ResultExtractor
    default_timeout_s: float | None = None
    stream_format: StreamFormat = "json"

    def resolve_cli_path(self) -> str:
        """Return the configured cli_path: env override > default.

        Reads ``self.cli_path_env`` from os.environ at call time so
        operators can change the binary without restarting the process
        (e.g. for canary testing a new claude build).
        """
        import os
        return os.environ.get(self.cli_path_env, self.default_cli_path)

    def build_mcp_flag_args(self, mcp_config_path: str | None) -> tuple[str, ...]:
        """Return argv args for the MCP flag, or empty tuple if unsupported.

        Returns empty when:
          - profile.mcp_flag_template is None (binary has no MCP)
          - mcp_config_path is None (executor opted out of MCP)
        """
        if not self.mcp_flag_template or mcp_config_path is None:
            return ()
        return tuple(self.mcp_flag_template.format(path=mcp_config_path).split())


# ---------------------------------------------------------------------------
# Registry (process-global singleton, populated by load_*_profiles at startup)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, CliProfile] = {}
_DISABLED: set[str] = set()  # profiles that failed to load — name kept for diagnostics

#: Defensive auto-load flag. Set True the first time _auto_load_builtins_if_needed
#: runs. reset_registry() clears it so tests can re-verify empty-registry paths.
_BUILTINS_AUTO_LOADED: bool = False


def _auto_load_builtins_if_needed() -> None:
    """Lazy-load builtin profiles on first registry query.

    Defends against entry points that import ``harness.engine.cli_profile``
    directly (the registry) without going through ``harness.cli_profiles``
    (the loader package). Symptom without this: server / CLI started before
    P3-T8 wires ``load_all_profiles_at_startup`` into lifespan → registry
    stays empty → ``get_profile("claude-code")`` raises spurious KeyError
    with ``valid options: []``.

    Idempotent via ``_BUILTINS_AUTO_LOADED``. Lazy import avoids the module
    cycle: ``cli_profiles/__init__.py`` reads types from this module but
    never calls this function.

    Failures are swallowed on purpose — the caller falls through to a
    KeyError / ValueError with diagnostic info, which is more actionable
    than a loader ImportError during early bootstrap.
    """
    global _BUILTINS_AUTO_LOADED
    if _BUILTINS_AUTO_LOADED:
        return
    _BUILTINS_AUTO_LOADED = True
    try:
        from harness.cli_profiles import load_builtin_profiles
        load_builtin_profiles()
    except Exception:
        # Loader unavailable (early bootstrap) or broken — let the caller
        # surface the empty-registry error. Logging here would be noise
        # because reset_registry re-arms and the next access retries.
        pass


def register_cli_profile(profile: CliProfile) -> None:
    """Register a CliProfile. Idempotent — last-write-wins.

    Called by load_builtin_profiles / load_project_profiles at startup,
    OR explicitly by tests / plugins. Raises if ``profile.name`` is empty.
    """
    if not profile.name:
        raise ValueError("CliProfile.name must be non-empty")
    _REGISTRY[profile.name] = profile
    # If re-registering a previously-disabled profile, clear the disable flag
    _DISABLED.discard(profile.name)


def disable_profile(name: str, reason: str) -> None:
    """Mark a profile as disabled (failed to load).

    Disabled profiles are excluded from VALID_EXECUTORS(). Using one raises
    a clear error pointing at the disable reason rather than a generic
    "unknown executor".
    """
    _DISABLED.add(name)
    # Stash the reason inside the registry's diagnostic info — kept simple
    # (string only) since this is for operator diagnostics, not programmatic
    # decisions. Real consumers use VALID_EXECUTORS() + get_profile().
    _DISABLED_REASONS[name] = reason


_DISABLED_REASONS: dict[str, str] = {}


def get_profile(name: str) -> CliProfile:
    """Look up a registered profile by name.

    Raises:
        KeyError: when name is not registered.
        ValueError: when name is registered but disabled (with reason).
    """
    _auto_load_builtins_if_needed()
    if name in _DISABLED:
        reason = _DISABLED_REASONS.get(name, "unknown reason")
        raise ValueError(
            f"executor {name!r} is disabled: {reason}. "
            "Fix the profile module and restart, or remove the workflow's "
            "executor field to use the default."
        )
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown executor {name!r}; valid options: "
            f"{sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def registered_profile_names() -> frozenset[str]:
    """Return all registered profile names (including disabled).

    Used by VALID_EXECUTORS() to merge with BUILTIN_EXECUTORS.
    """
    _auto_load_builtins_if_needed()
    return frozenset(_REGISTRY.keys()) | frozenset(_DISABLED)


def disabled_profile_diagnostics() -> dict[str, str]:
    """Return disabled profile names → reason. For operator diagnostics."""
    return dict(_DISABLED_REASONS)


def reset_registry() -> None:
    """Clear the registry (tests only).

    Re-arms ``_BUILTINS_AUTO_LOADED`` so the next ``get_profile`` /
    ``registered_profile_names`` call re-triggers the lazy builtin load —
    mirrors the "fresh process" semantics tests rely on.
    """
    global _BUILTINS_AUTO_LOADED
    _REGISTRY.clear()
    _DISABLED.clear()
    _DISABLED_REASONS.clear()
    _BUILTINS_AUTO_LOADED = False
