# Release: CliProfile Abstraction + User-Defined CLI Backends (Phase 3 of executor-extensibility refactor)

**Date**: 2026-06-26
**Phase**: 3 of 3 (Phase 1 = Prompt Paradigm Split; Phase 2 = ErrorEvent contract)
**ADR**: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md) (Status: Accepted)
**Plan**: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## What changed

Replaces the hardcoded claude-CLI configuration with a CliProfile protocol + project-level override discovery. Operators can now add a new CLI backend (opencode / codex / canary claude build) by writing one Python file — no core code changes needed.

| File | Change |
|---|---|
| `harness/engine/cli_profile.py` (new in P3-T1) | `CliProfile` dataclass + `CliSpawnConfig` / `CliRunResult` + registry (`register_cli_profile` / `get_profile` / `disable_profile` / `registered_profile_names`) |
| `harness/engine/_cli_subprocess.py` (new in P3-T2) | Generic `run_cli(cfg, profile, on_line, timeout)` — profile-agnostic spawn + stream + drain |
| `harness/cli_profiles/__init__.py` (new in P3-T3) | `load_builtin_profiles` + `load_project_profiles` + `load_all_profiles_at_startup` + graceful degradation (broken profile → disable with reason) |
| `harness/cli_profiles/claude.py` (new in P3-T3) | Builtin `PROFILE = CliProfile(name="claude-code", ...)` — flags migrated verbatim from `_claude_subprocess.DEFAULT_FLAGS` |
| `harness/engine/claude_code_executor.py` (P3-T4) | `__init__` accepts `profile: CliProfile \| None`; profile drives `executor` name in ErrorEvent + result extractor |
| `harness/core/agent.py` (P3-T5) | `VALID_EXECUTORS` is now a FUNCTION (dynamic merge with profile registry); `BUILTIN_EXECUTORS` is the static set |
| `harness/engine/executor_factory.py` (P3-T6) | `make_executor` dispatches via `get_profile(backend)` → `ClaudeCodeExecutor(profile=...)`; removed hardcoded `if backend == "claude-code"` branch |
| `harness/engine/claude_code_executor.py::_load_env_overlay` (P3-T7) | Reads `profile.env_overlay_prefixes` (was hardcoded ANTHROPIC_/CLAUDE_); adds `HARNESS_<NAME>_ENV_<KEY>` override layer with per-profile isolation |
| `server/app.py` + `harness/cli.py` (P3-T8) | `load_all_profiles_at_startup()` at server lifespan + CLI main entry |
| `harness/cli_profiles/__init__.py::_load_profile_from_path` (P3-T9) | Returns `(profile, reason)` tuple → disable messages carry the actual error (e.g. "SyntaxError: invalid syntax (foo.py, line 1)") |
| `README.md` (P3-T10) | New "执行器与 CLI Profile" section with full authoring recipe + env configuration + error handling |
| `CLAUDE.md` (P3-T10) | New "执行器与 CLI Profile 契约" section listing 4 load-bearing invariants |

## Why

Three problems the previous architecture had:

1. **Claude CLI hardcoded**: `_claude_subprocess.DEFAULT_FLAGS` was a tuple of claude-specific flags; adding opencode required changing core spawn code. No way for users to canary a different claude build.

2. **No project-level customization**: operators could not override the claude-code behavior for a specific project (different gateway / different binary path) without editing installed package files.

3. **VALID_EXECUTORS was a closed set**: adding a new executor name required editing the frozenset + executor_factory `if` branch + the agent whitelist check — three places, easy to forget one.

## Solution

### CliProfile protocol (P3-T1)

```python
@dataclass
class CliProfile:
    name: str                          # "claude-code" / "opencode" / ...
    prompt_paradigm: PromptParadigm    # "pydantic-ai" | "minimal"
    cli_path_env: str                  # "HARNESS_CLAUDE_CLI"
    default_cli_path: str              # "claude"
    flags: tuple[str, ...]             # ("-p", "--output-format", "stream-json", ...)
    prompt_channel: PromptChannel      # "stdin" | "argv"
    mcp_flag_template: str | None      # "--mcp-config {path}" | None
    env_overlay_prefixes: tuple[str, ...]  # ("ANTHROPIC_", "CLAUDE_")
    translator: Translator             # stream-json → harness events
    result_extractor: ResultExtractor  # final text → structured output
    default_timeout_s: float | None    # wall-clock timeout
```

Profile methods:
- `resolve_cli_path()` — env override > default
- `build_mcp_flag_args(path)` — template render; empty when no MCP support

Registry API: `register_cli_profile` / `get_profile` / `disable_profile` / `registered_profile_names` / `disabled_profile_diagnostics` / `reset_registry`.

### Persistence contract (P3-T3)

Profile discovery mirrors `harness/config.py:15-20` `.env` fallback:
1. `$HARNESS_CLI_PROFILES_DIR/<name>.py` (env override)
2. `<cwd>/.harness/cli_profiles/<name>.py` (project-level, highest default priority)
3. `harness/cli_profiles/<name>.py` (builtin)

Same-name profiles: project overrides builtin (last-write-wins registration order).

### Dynamic VALID_EXECUTORS (P3-T5)

```python
BUILTIN_EXECUTORS = frozenset({"pydantic-ai", "claude-code"})

def VALID_EXECUTORS() -> frozenset[str]:
    return BUILTIN_EXECUTORS | registered_profile_names()
```

Registering a profile automatically extends the valid executor set. Agent construction with the new name succeeds without whitelist edits.

### Profile-aware env overlay (P3-T7)

```
.env:                                    # layer 1 — profile-declared prefixes
  ANTHROPIC_AUTH_TOKEN=...

HARNESS_CLAUDE_CODE_ENV_ANTHROPIC_BASE_URL=https://canary  # layer 2 — per-profile override
```

Layer 2 wins. Per-profile isolation by name normalization (`claude-code` → `CLAUDE_CODE`).

### Graceful degradation (P3-T9)

Broken profile (syntax error / missing PROFILE / wrong type) → `disable_profile(name, reason)` with the SPECIFIC error message. Startup continues; other profiles load. Using the disabled profile raises `ValueError` with the reason.

## Acceptance

### Automated (367 backend tests green across P1 + P2 + P3)

| Test file | Cases |
|---|---|
| `tests/engine/test_cli_profile_dataclass.py` | 17 |
| `tests/engine/test_cli_profile_registry.py` | 15 |
| `tests/engine/test_cli_profile_startup_degradation.py` | 8 |
| `tests/engine/test_run_cli.py` | 9 |
| `tests/engine/test_claude_code_executor_profile.py` | 5 |
| `tests/engine/test_claude_code_executor_env_overlay.py` | 5 |
| `tests/engine/test_executor_factory_profile_dispatch.py` | 5 |
| `tests/engine/test_custom_profile_e2e_mock.py` | 5 |
| + all P1 / P2 regression | 298 |

### Real-subprocess e2e (manual)

1. Write `./.harness/cli_profiles/opencode.py` exporting `PROFILE = CliProfile(name="opencode", ...)`
2. Start `uvicorn server.main:app` (lifespan auto-discovers the profile)
3. Run a workflow with `executor: "opencode"`
4. Verify ClaudeCodeExecutor runs with the opencode profile (cli path / flags / translator)
5. Error case: bad OPENCODE_TOKEN → `agent.executor_error` with `executor: "opencode"`

## Commit SHAs (Phase 3)

- `1ed345c` — P3-T1: CliProfile dataclass + registry framework
- `c450c7f` — P3-T2: generic run_cli replacing run_claude
- `72db962` — P3-T3: cli_profiles package + claude builtin profile
- `2737721` — P3-T4: ClaudeCodeExecutor profile-driven configuration
- `949ba1d` — P3-T5: VALID_EXECUTORS dynamic with profile registry
- `e3afe3c` — P3-T6: executor_factory dispatch via profile registry
- `bec1466` — P3-T7: profile-aware env overlay + per-profile env override
- `2431505` — P3-T8: load builtin + project CLI profiles at startup
- `09ba8c7` — P3-T9: graceful degradation with detailed disable reasons
- `b5bdbdc` — P3-T10: document custom CLI profile authoring
- `3fa1925` — P3-T11: e2e mock test for custom opencode profile

## Out of scope (follow-up work)

- Real opencode / codex builtin profiles (this refactor lands the framework; specific backends are separate PRs)
- CliExecutorBase extraction (ClaudeCodeExecutor currently holds all the logic; a future refactor can extract a shared base for further backends if patterns emerge)
- Profile versioning / migration (profiles are Python modules — bump via git, no schema migration needed)
