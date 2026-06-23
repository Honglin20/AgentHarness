"""TASK 5 acceptance: enhanced tool descriptions carry decision rules.

Verifies the bash/grep/glob descriptions now embed the tool-selection and
failure-handling rules that were previously duplicated across agent.md
files. Each description must contain the key decision phrases so agents
inherit correct tool choice without per-agent restating.
"""
from __future__ import annotations

from harness.tools.bash import BashToolFactory
from harness.tools.grep_glob import GrepToolFactory, GlobToolFactory


def _desc(factory_cls) -> str:
    return factory_cls.description


# --- bash: tool selection + destructive + timeout ---

def test_bash_prefers_dedicated_tools():
    d = _desc(BashToolFactory)
    assert "dedicated" in d.lower()
    assert "grep" in d.lower()  # names the alternatives


def test_bash_flags_destructive_commands():
    d = _desc(BashToolFactory)
    assert "destructive" in d.lower()
    assert "rm" in d  # concrete example


def test_bash_handles_timeout():
    d = _desc(BashToolFactory)
    assert "timeout" in d.lower()
    assert "split" in d.lower() or "narrow" in d.lower()  # remediation hint


def test_bash_mentions_output_spill():
    d = _desc(BashToolFactory)
    assert "read_text_file" in d  # points to paging mechanism


# --- grep: scope-first + no-match guidance ---

def test_grep_distinguishes_from_glob():
    d = _desc(GrepToolFactory)
    assert "Glob" in d  # names the sibling tool
    assert "PATHS" in d or "paths" in d  # clarifies glob's job


def test_grep_no_match_guidance():
    d = _desc(GrepToolFactory)
    assert "no match" in d.lower() or "no matches" in d.lower()


# --- glob: scope-before-grep + no-match guidance ---

def test_glob_runs_before_grep():
    d = _desc(GlobToolFactory)
    assert "Grep" in d
    assert "BEFORE" in d or "before" in d


def test_glob_no_match_guidance():
    d = _desc(GlobToolFactory)
    assert "no match" in d.lower() or "too narrow" in d.lower()


# --- budget: descriptions must not bloat context ---

def test_tool_descriptions_within_budget():
    """Each description stays under ~2KB so it doesn't dominate context."""
    for cls in (BashToolFactory, GrepToolFactory, GlobToolFactory):
        size = len(_desc(cls).encode("utf-8"))
        assert size < 2000, f"{cls.__name__}.description is {size} bytes (limit 2000)"


def test_descriptions_have_no_domain_terms():
    """Tool descriptions must stay domain-free (no NAS/quant/distill)."""
    forbidden = ("nas", "quant", "distill", "mnist", "onnx", "epoch")
    for cls in (BashToolFactory, GrepToolFactory, GlobToolFactory):
        d = _desc(cls).lower()
        for term in forbidden:
            assert term not in d, f"{cls.__name__} contains domain term '{term}'"
