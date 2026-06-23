"""Baseline snapshot for the prompt-tools-and-runtime refinement plan.

Captures the CURRENT (pre-refinement) state of everything the 6 TASKs touch,
so each TASK can prove its change by diffing against this baseline:

  - TASK 1 (tool descriptions): records each tool's current description text +
    length, so post-change we can show length < 2KB and the new key phrases
    appeared (sub_agent gaining "delegate/parallel/worktree").
  - TASK 2 (failure write-end): proves last_tool_failure is NEVER written by
    any tool today (the empty pipe is the bug). Post-TASK-2 a bash timeout
    must populate it.
  - TASK 3 (feedback language): records the current zh/en mix so post-change
    we can show zero CJK remaining.
  - TASK 4 (base.md dedup): records that base.md STILL contains the tool-
    selection rules that duplicate tool descriptions (the DRY violation).
    Post-TASK-4 those strings are gone from base.md.
  - TASK 5 (iteration): proves runtime_status today emits NO iteration block
    (deps.iteration ignored). Post-TASK-5 iteration>1 surfaces it.
  - TASK 6 (reminders pipeline): proves deps has no pending_reminders field
    and runtime_status has no reminders block. Post-TASK-6 the field + flush
    block exist.

This is a PURE-LOGIC baseline (no LLM, no network) — fast and deterministic.
The behavioral (real-LLM) contract stays in test_prompt_demo_behavior.py.

Run:
    python -m pytest tests/test_prompt_refinement_baseline.py -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness.prompts import assembler as assembler_mod
from harness.prompts import feedback
from harness.prompts.assembler import assemble_static_prompt
from harness.prompts.runtime import _failure_block, _todo_status_block, runtime_status
from harness.tools.deps import AgentDeps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# CJK Unicode range detector — used by TASK 3 to prove English-only feedback.
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def _make_ctx(deps: AgentDeps):
    """Build a minimal RunContext-like object carrying deps."""
    class _Ctx:
        def __init__(self, d):
            self.deps = d
    return _Ctx(deps)


# ---------------------------------------------------------------------------
# TASK 1 baseline — current tool descriptions (length + key-phrase absence)
# ---------------------------------------------------------------------------

def _tool_descriptions() -> dict[str, str]:
    """Collect the description attribute of every built-in ToolFactory.

    Imports are local so a missing optional dep (mcp) doesn't break the whole
    baseline. Returns name → description string.
    """
    from harness.tools.bash import BashToolFactory
    from harness.tools.grep_glob import GrepToolFactory, GlobToolFactory
    from harness.tools.sub_agent import SubAgentToolFactory
    from harness.tools.todo import TodoToolFactory
    from harness.tools.ask_user import AskUserToolFactory
    from harness.tools.chart import RenderChartToolFactory

    factories = {
        "bash": BashToolFactory,
        "grep": GrepToolFactory,
        "glob": GlobToolFactory,
        "sub_agent": SubAgentToolFactory,
        "TodoTool": TodoToolFactory,
        "ask_user": AskUserToolFactory,
        "render_chart": RenderChartToolFactory,
    }
    return {name: getattr(f, "description", "") for name, f in factories.items()}


def test_task1_baseline_records_current_tool_descriptions():
    """All 7 built-in tools have a description (none empty)."""
    descs = _tool_descriptions()
    assert set(descs) == {
        "bash", "grep", "glob", "sub_agent", "TodoTool", "ask_user", "render_chart",
    }
    for name, d in descs.items():
        assert d, f"{name} has an empty description — TASK 1 must not regress this"


def test_task1_sub_agent_has_decision_guidance():
    """TASK 1 acceptance: sub_agent now carries delegation DECISION guidance.

    Pre-refinement it only described mechanics (launch/parallel/worktree) with
    no WHEN-to-delegate advice. TASK 1 adds the decision layer (delegate vs
    do-it-yourself) that CC's Task tool provides.
    """
    descs = _tool_descriptions()
    sa = descs["sub_agent"].lower()
    # Mechanics retained.
    assert "parallel" in sa and "worktree" in sa
    # Decision language NOW present (TASK 1 closed the gap).
    assert "delegate" in sa, "sub_agent must advise when to delegate"
    assert "when to delegate" in sa, (
        "sub_agent needs a structured WHEN-TO-DELEGATE section"
    )


@pytest.mark.parametrize("name", list(_tool_descriptions().keys()))
def test_task1_all_descriptions_under_2kb_and_english(name):
    """TASK 1 acceptance: every tool description < 2KB and English-only."""
    descs = _tool_descriptions()
    d = descs[name]
    assert len(d) < 2000, f"{name} description {len(d)} chars exceeds 2KB budget"
    assert not _has_cjk(d), f"{name} description contains CJK — must be English"


def test_task1_grep_has_output_mode_and_regex_guidance():
    """TASK 1 acceptance: grep now guides output_mode choice + regex escaping."""
    descs = _tool_descriptions()
    g = descs["grep"].lower()
    assert "output mode" in g, "grep must explain output_mode choices"
    assert "escape" in g, "grep must warn about regex metacharacter escaping"


# ---------------------------------------------------------------------------
# TASK 2 baseline — last_tool_failure is never written (the bug)
# ---------------------------------------------------------------------------

def test_task2_baseline_no_tool_writes_last_tool_failure():
    """No built-in tool touches deps.last_tool_failure today.

    grep the tool source for the attribute. This is the documented half-finished
    state from the refactor release note. TASK 2 must make this assertion FAIL
    (bash/grep error paths start writing it).
    """
    import harness.tools.bash as bash_mod
    import harness.tools.grep_glob as grep_mod

    for mod_name, mod in (("bash", bash_mod), ("grep_glob", grep_mod)):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "last_tool_failure" not in src, (
            f"{mod_name} already writes last_tool_failure — TASK 2 may be done"
        )


def test_task2_baseline_failure_block_returns_empty_with_real_deps():
    """With a fresh AgentDeps, _failure_block returns '' (nothing was written).

    Post-TASK-2, after a bash timeout writes the failure, this same deps would
    surface it. The baseline deps here never had a tool run, so it's empty.
    """
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    assert _failure_block(deps) == ""
    assert deps.last_tool_failure is None


# ---------------------------------------------------------------------------
# TASK 3 baseline — feedback.py is currently zh/en mixed
# ---------------------------------------------------------------------------

def test_task3_baseline_feedback_has_cjk_today():
    """step_gate-style feedback messages are currently Chinese.

    This is the documented zh/en mix. TASK 3 must make this assertion FAIL
    (all feedback becomes English). Recorded here so the language contract is
    explicit: today CJK is present, post-TASK-3 it is not.
    """
    cjk_funcs = {
        "todo_not_created_msg": feedback.todo_not_created_msg(),
        "reminder_create_msg": feedback.reminder_create_msg(),
        "reminder_update_idle_msg": feedback.reminder_update_idle_msg(),
    }
    present = {name for name, s in cjk_funcs.items() if _has_cjk(s)}
    assert present, (
        "no CJK in feedback — TASK 3 may be done. Expected Chinese today."
    )


def test_task3_baseline_schema_retry_is_already_english():
    """schema_retry_msg is already English — TASK 3 must NOT change it."""
    msg = feedback.schema_retry_msg("final_result", '{"type":"object"}')
    assert not _has_cjk(msg), "schema_retry_msg must stay English"


# ---------------------------------------------------------------------------
# TASK 4 baseline — base.md still duplicates tool-selection rules (DRY violation)
# ---------------------------------------------------------------------------

def test_task4_base_md_no_longer_duplicates_tool_rules():
    """TASK 4 acceptance: base.md must NOT duplicate tool-description rules.

    The tool-selection rules (prefer dedicated grep/glob over bash, how to
    handle destructive commands, what to do on timeout) now live ONLY in each
    tool's description. base.md keeps the one cross-tool coordination rule
    (glob-then-grep) but drops the duplicated per-tool guidance.
    """
    base = assembler_mod._load_base_layer()
    # These strings were the DRY violation — they appeared in BOTH base.md and
    # the bash/grep tool descriptions. They must now be GONE from base.md.
    removed_markers = ["Choose the right tool", "Prefer the dedicated"]
    for m in removed_markers:
        assert m not in base, (
            f"base.md still contains {m!r} — TASK 4 did not complete the dedup"
        )
    # The cross-tool coordination rule is KEPT (not a per-tool rule).
    assert "glob" in base.lower() and "grep" in base.lower(), (
        "base.md must retain the glob-then-grep coordination rule"
    )


# ---------------------------------------------------------------------------
# TASK 5 baseline — runtime_status emits no iteration block today
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task5_baseline_no_iteration_block():
    """runtime_status ignores deps.iteration today (no iteration surfacing).

    Post-TASK-5, the same deps with iteration=3 must surface an iteration
    block. Today it does not. This baseline proves the field is read nowhere.
    """
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a", iteration=5)
    # No todo plan + no failure → currently returns the "no plan yet" block only.
    out = await runtime_status(_make_ctx(deps))
    assert "iteration" not in out.lower(), (
        "runtime_status already surfaces iteration — TASK 5 may be done"
    )


# ---------------------------------------------------------------------------
# TASK 6 baseline — no reminders pipeline yet
# ---------------------------------------------------------------------------

def test_task6_baseline_deps_has_no_reminders_field():
    """AgentDeps has no pending_reminders field today.

    TASK 6 adds it. Pydantic model_config has extra='allow', so we check the
    declared fields, not attribute access (extra='allow' would let us SET
    anything). This asserts the field is NOT declared.
    """
    declared = set(AgentDeps.model_fields)
    assert "pending_reminders" not in declared, (
        "AgentDeps already declares pending_reminders — TASK 6 may be done"
    )


# ---------------------------------------------------------------------------
# Structural baseline dump — write a JSON snapshot for before/after diff
# ---------------------------------------------------------------------------

BASELINE_DUMP = Path(__file__).resolve().parent / "fixtures" / "prompt_baseline" / "refinement_before.json"


def test_dump_refinement_baseline_snapshot():
    """Write a JSON snapshot of the pre-refinement state for before/after diff.

    Not an assertion — a recorder. Run before TASKs to capture 'before', run
    after to capture 'after', diff the two. Idempotent + deterministic.
    """
    descs = _tool_descriptions()
    base = assembler_mod._load_base_layer()

    snapshot = {
        "task1_tool_descriptions": {
            name: {"chars": len(d), "has_cjk": _has_cjk(d), "text": d}
            for name, d in descs.items()
        },
        "task2_failure_write_end_absent": True,  # proven by test_task2_baseline_*
        "task3_feedback_cjk_present": {
            "todo_not_created_msg": _has_cjk(feedback.todo_not_created_msg()),
            "reminder_create_msg": _has_cjk(feedback.reminder_create_msg()),
            "schema_retry_msg_english": not _has_cjk(
                feedback.schema_retry_msg("final_result", '{}')
            ),
        },
        "task4_base_md_has_tool_selection_dup": "Choose the right tool" in base,  # False after TASK 4
        "task5_runtime_has_iteration_block": False,  # proven by test_task5_baseline_*
        "task6_deps_has_reminders_field": False,  # proven by test_task6_baseline_*
        "assembled_prompt_total_chars": len(
            assemble_static_prompt("# Demo\n\nBody.", None)
        ),
    }
    BASELINE_DUMP.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_DUMP.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    # Sanity: snapshot is well-formed JSON round-trip.
    assert json.loads(BASELINE_DUMP.read_text(encoding="utf-8")) == snapshot
