import tempfile
from pathlib import Path
from harness.compiler.md_parser import parse_agent_md, write_agent_md


def test_write_and_reparse_agent_md():
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "test_agent.md"
        write_agent_md(
            path=md_path,
            name="test_agent",
            prompt="You are a test agent.\nDo the thing.",
            tools=["bash", "read_file"],
            model="deepseek:deepseek-chat",
            retries=5,
        )
        parsed = parse_agent_md(md_path)
        assert parsed.name == "test_agent"
        assert "You are a test agent" in parsed.prompt
        assert parsed.tools == ["bash", "read_file"]
        assert parsed.model == "deepseek:deepseek-chat"
        assert parsed.retries == 5


def test_update_preserves_unmodified_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "test_agent.md"
        write_agent_md(md_path, name="a", prompt="v1", tools=["bash"], model=None, retries=3)
        write_agent_md(md_path, name="a", prompt="v2", tools=["bash"], model=None, retries=3)
        parsed = parse_agent_md(md_path)
        assert parsed.prompt == "v2"
        assert parsed.tools == ["bash"]
