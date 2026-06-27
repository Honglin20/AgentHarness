# Release: Prompt Paradigm Split (Phase 1 of executor-extensibility refactor)

**Date**: 2026-06-26
**Phase**: 1 of 3 (Phase 2 = ErrorEvent contract; Phase 3 = CliProfile abstraction)
**ADR**: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md)
**Plan**: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## What changed

Split `harness/prompts/base.md` into two paradigm-specific files and dispatch the assembler by executor, so CLI backends (claude-code/codex/opencode) stop being force-fed pydantic-ai-only tool contracts.

| File | Before | After |
|---|---|---|
| `harness/prompts/base.md` | Single file with `TodoTool MUST` + `final_result tool` contracts | **Deleted** |
| `harness/prompts/base_pydantic.md` | — | New; byte-identical to pre-split `base.md` |
| `harness/prompts/base_minimal.md` | — | New; same working norms without pydantic-ai-only tool references |
| `harness/prompts/assembler.py` | Single base path + single output-format template | `_BASE_MD_PATHS` dict by paradigm + `_OUTPUT_FORMAT_MINIMAL_TEMPLATE` + `executor` kwarg on `assemble_static_prompt` + `executor_to_paradigm` mapping + `register_executor_paradigm` override hook |
| `harness/engine/node_factory.py:117` | `if result_type is not None: assemble_static_prompt(body, rt)` | Always `assemble_static_prompt(body, rt, executor=agent_def.executor)` — fixes pre-existing bug where free-text agents skipped base injection |

## Why

ask_user_demo/greeter under claude-code executor was not calling `mcp__harness__ask_user`. Root cause: ClaudeCodeExecutor passed the assembled prompt to `claude -p --append-system-prompt`, but the prompt told the model "Your first action MUST be `TodoTool(op='create', ...)`" and "call the `final_result` tool" — neither tool exists on the claude-code path. The model was derailed by instructions to call non-existent tools.

## Acceptance

### Automated (70 tests green)

| Test file | Cases | Locks |
|---|---|---|
| `tests/test_prompt_paradigm_split.py` | 5 | base_pydantic byte-identical / base_minimal excludes pydantic-ai contracts / legacy base.md removed / assembler default unchanged |
| `tests/test_prompt_executor_paradigm.py` | 22 | executor→paradigm mapping / pydantic output keeps `final_result` / minimal output excludes it / register_executor_paradigm override + idempotency / fail-loud on unknown paradigm |
| `tests/test_node_factory_prompt_dispatch.py` | 5 | executor dispatched through call site / free-text agents still get base / ValueError propagates / non-ValueError falls back with WARNING |
| `tests/test_prompt_baseline_minimal.py` | 16 | minimal_assemble byte-level fixtures / minimal manifest sha256 audit / ask_user_demo greeter prompt excludes TodoTool/final_result/complete_remaining |
| `tests/test_prompt_baseline.py` | 7 | pydantic-ai path byte-stable (regression gate) |
| `tests/test_prompt_assembler.py` | 16 | pydantic-ai path byte-stable / base layer prefix invariant |

### Offline e2e (real claude -p smoke)

Spawned `claude -p` with the assembled ask_user_demo/greeter prompt. Model output:

> "I cannot run this task as written. The agent prompt requires me to call an `ask_user` tool as my very first action, but **no such tool exists in my environment**."
>
> | Required by prompt | Actually available |
> |---|---|
> | `ask_user` | `AskUserQuestion` |

This is the proof that P1 worked: the model correctly identified the `ask_user` requirement from agent MD (no longer derailed by phantom `final_result`/`TodoTool`). The "no such tool" failure is expected — `ask_user` is provided by harness MCP server, which `ClaudeCodeExecutor._setup_mcp()` starts at runtime; this smoke test deliberately skipped MCP setup.

### Full e2e (manual, requires server + frontend)

Not automated. Steps:
1. Start `uvicorn server.main:app` + frontend dev server
2. Open browser, select `ask_user_demo` workflow, click Run
3. Verify `agent.tool_call` event fires with `tool_name=mcp__harness__ask_user`
4. Verify question card renders, user answers, `agent.tool_result` event fires
5. Verify workflow continues to `survey` agent

## Not in scope

- **Translation layer for `system/api_retry` / `system/status`** — Phase 2
- **CliProfile abstraction for opencode/codex** — Phase 3
- **MCP server lifecycle changes** — ClaudeCodeExecutor already sets up MCP correctly; P1 only fixed the prompt content

## Commit SHAs

- `1660ef6` — `refactor(prompt): P1-T1 split base.md into paradigm-specific files`
- `9f538e9` — `feat(prompt): P1-T2 add executor-aware assembler + minimal output format`
- `ce4456f` — `feat(prompt): P1-T3 wire executor arg through node_factory + fix free-text base loss`
- `a71e0ab` — `test(prompt): P1-T4 minimal baseline fixtures + ask_user_demo acceptance`

## Deviations from plan

- **P1-T3 scope creep (blessed by reviewer)**: Plan said only "wire executor arg through", but the existing `if result_type is not None:` guard structurally blocked free-text agents from receiving any base layer. Fixing the guard was correctly grouped into P1-T3 because splitting would force a no-op intermediate commit (the executor dispatch can't work without all agents reaching the assembler).
- **P1-T3 fail-loud hardening**: Reviewer flagged that `except Exception` would swallow P1-T2's intentional `ValueError` on unknown paradigm. Narrowed to `except ValueError: raise` before the generic fallback. This is a contract tightening, not a behavior change.

## Verification results

- `make test` equivalent: `python -m pytest tests/ --ignore=tests/server` → 1161 passed, 25 pre-existing failures unchanged (zero new failures introduced across Phase 1)
- Pre-existing `tests/extensions/test_tool_hooks.py::test_a4_rewrite_exception_falls_back_to_original_args` fails identically before and after Phase 1 (test-isolation bug, unrelated)
