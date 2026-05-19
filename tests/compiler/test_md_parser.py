import pytest
from pathlib import Path
from harness.compiler.md_parser import parse_agent_md, ParsedAgent

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_full_frontmatter():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert isinstance(result, ParsedAgent)
    assert result.name == "refactorer"
    assert result.tools == ["bash", "fs"]
    assert result.model == "claude-sonnet-4-6"
    assert result.retries == 3
    assert "代码重构专家" in result.prompt


def test_parse_minimal_frontmatter():
    md = FIXTURES / "minimal_agent.md"
    result = parse_agent_md(md)
    assert result.name == "analyzer"
    assert result.tools == []
    assert result.model is None
    assert result.retries == 3  # default


def test_parse_extracts_description():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert result.description == "你是一个代码重构专家"


def test_parse_no_frontmatter_raises():
    md = FIXTURES / "no_frontmatter.md"
    with pytest.raises(ValueError, match="frontmatter"):
        parse_agent_md(md)


def test_parse_missing_name_raises():
    md = FIXTURES / "missing_name.md"
    with pytest.raises(ValueError, match="name"):
        parse_agent_md(md)


def test_parse_prompt_is_stripped():
    md = FIXTURES / "full_agent.md"
    result = parse_agent_md(md)
    assert not result.prompt.startswith("\n")
    assert not result.prompt.endswith("\n")
