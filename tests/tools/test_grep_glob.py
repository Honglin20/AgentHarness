import os
import tempfile

import pytest

from harness.tools.grep_glob import _find_rg, GrepToolFactory, GlobToolFactory
from harness.tools.registry import ToolRegistry


# ── helpers ──────────────────────────────────────────────────────


@pytest.fixture
def sample_project(tmp_path):
    """Create a small project tree for testing."""
    (tmp_path / "main.py").write_text("def hello():\n    print('hello')\n\ndef world():\n    print('world')\n")
    (tmp_path / "utils.py").write_text("def helper(x):\n    return x * 2\n")
    (tmp_path / "README.md").write_text("# My Project\n\nHello world\n")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "app.py").write_text("from utils import helper\n\ndef run():\n    helper(42)\n")
    return tmp_path


@pytest.fixture
def registry(sample_project):
    reg = ToolRegistry()
    reg.register("grep", GrepToolFactory())
    reg.register("glob", GlobToolFactory())
    return reg


def _run_tool(registry, tool_name, **kwargs):
    """Resolve tool and call it with a minimal fake context."""
    from pydantic_ai import RunContext
    from harness.tools.deps import AgentDeps

    deps = AgentDeps(workdir=os.getcwd())
    ctx = RunContext(deps=deps, model=None, usage=None, prompt=None)
    tools = registry.resolve([tool_name])
    # Find the right tool by name
    tool = next(t for t in tools if getattr(t, 'name', None) == tool_name or tool_name in str(getattr(t, '_function', '')))
    # Use the factory's create() directly instead
    factory = registry._factories[tool_name]
    pydantic_tool = factory.create()
    fn = pydantic_tool.function
    return fn(ctx, **kwargs)


# ── _find_rg ─────────────────────────────────────────────────────


def test_find_rg():
    rg = _find_rg()
    # rg should be available on this machine (conda)
    assert rg is not None


# ── grep ─────────────────────────────────────────────────────────


class TestGrep:
    def test_grep_finds_pattern(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="def hello", path=str(sample_project))
        assert "main.py" in result

    def test_grep_content_mode(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="def", path=str(sample_project), output_mode="content")
        assert "def hello" in result
        assert "def world" in result

    def test_grep_count_mode(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="def", path=str(sample_project), output_mode="count")
        assert "main.py" in result

    def test_grep_type_filter(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="Hello", path=str(sample_project), type="md")
        assert "README.md" in result
        assert "main.py" not in result

    def test_grep_case_insensitive(self, registry, sample_project):
        result_ci = _run_tool(registry, "grep", pattern="HELLO", path=str(sample_project), case_insensitive=True)
        result_cs = _run_tool(registry, "grep", pattern="HELLO", path=str(sample_project))
        assert "hello" in result_ci.lower()
        assert "No matches" in result_cs

    def test_grep_glob_filter(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="def", path=str(sample_project), glob="*.py")
        assert "README.md" not in result

    def test_grep_no_matches(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="zzzznonexistent", path=str(sample_project))
        assert "No matches" in result

    def test_grep_context_lines(self, registry, sample_project):
        result = _run_tool(registry, "grep", pattern="def hello", path=str(sample_project), output_mode="content", context=1)
        assert "print" in result


# ── glob ─────────────────────────────────────────────────────────


class TestGlob:
    def test_glob_python_files(self, registry, sample_project):
        result = _run_tool(registry, "glob", pattern="*.py", path=str(sample_project))
        assert "main.py" in result
        assert "utils.py" in result

    def test_glob_recursive(self, registry, sample_project):
        result = _run_tool(registry, "glob", pattern="**/*.py", path=str(sample_project))
        assert "app.py" in result
        assert "main.py" in result

    def test_glob_no_matches(self, registry, sample_project):
        result = _run_tool(registry, "glob", pattern="*.java", path=str(sample_project))
        assert "No files" in result

    def test_glob_md_files(self, registry, sample_project):
        result = _run_tool(registry, "glob", pattern="*.md", path=str(sample_project))
        assert "README.md" in result
        assert ".py" not in result
