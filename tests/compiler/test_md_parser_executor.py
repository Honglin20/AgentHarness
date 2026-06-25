"""Phase A — md_parser 的 executor 字段单元测试。

验收锚点（对应 detailed-design.md §4.3）：
  1. frontmatter 缺 executor → 默认 ``"pydantic-ai"``
  2. frontmatter 显式 claude-code → 正确解析
  3. frontmatter 非法值 → ValueError
  4. write_agent_md 默认值不写盘（最小 diff）
  5. write_agent_md 非默认值写盘
"""
from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from harness.compiler.md_parser import parse_agent_md, write_agent_md


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "agent.md"
    p.write_text(body)
    return p


class TestParseAgentMdExecutor:
    def test_default_when_field_absent(self, tmp_path):
        p = _write(tmp_path, "---\nname: a\n---\n\nbody\n")
        parsed = parse_agent_md(p)
        assert parsed.executor == "pydantic-ai"

    def test_explicit_claude_code(self, tmp_path):
        p = _write(tmp_path, "---\nname: a\nexecutor: claude-code\n---\n\nbody\n")
        parsed = parse_agent_md(p)
        assert parsed.executor == "claude-code"

    def test_explicit_pydantic_ai(self, tmp_path):
        p = _write(tmp_path, "---\nname: a\nexecutor: pydantic-ai\n---\n\nbody\n")
        parsed = parse_agent_md(p)
        assert parsed.executor == "pydantic-ai"

    def test_invalid_executor_raises(self, tmp_path):
        p = _write(tmp_path, "---\nname: a\nexecutor: bogus\n---\n\nbody\n")
        with pytest.raises(ValueError, match=r"executor must be one of"):
            parse_agent_md(p)

    def test_invalid_executor_error_lists_valid_options(self, tmp_path):
        p = _write(tmp_path, "---\nname: a\nexecutor: custom\n---\n\nbody\n")
        with pytest.raises(ValueError) as exc:
            parse_agent_md(p)
        msg = str(exc.value)
        assert "pydantic-ai" in msg
        assert "claude-code" in msg

    def test_other_fields_still_parsed_alongside_executor(self, tmp_path):
        p = _write(
            tmp_path,
            "---\nname: a\nexecutor: claude-code\ntools:\n  - bash\n  - read_file\nmodel: sonnet\nretries: 5\n---\n\nbody\n",
        )
        parsed = parse_agent_md(p)
        assert parsed.executor == "claude-code"
        assert parsed.tools == ["bash", "read_file"]
        assert parsed.model == "sonnet"
        assert parsed.retries == 5


class TestWriteAgentMdExecutor:
    def test_default_executor_not_written(self, tmp_path):
        """最小 diff 原则：默认值不写盘。"""
        p = tmp_path / "agent.md"
        write_agent_md(p, name="a", prompt="body")
        content = p.read_text()
        assert "executor" not in content

    def test_explicit_default_not_written(self, tmp_path):
        """显式传 ``executor='pydantic-ai'`` 也不写盘（语义同默认）。"""
        p = tmp_path / "agent.md"
        write_agent_md(p, name="a", prompt="body", executor="pydantic-ai")
        content = p.read_text()
        assert "executor" not in content

    def test_claude_code_is_written(self, tmp_path):
        p = tmp_path / "agent.md"
        write_agent_md(p, name="a", prompt="body", executor="claude-code")
        content = p.read_text()
        assert "executor: claude-code" in content

    def test_roundtrip_claude_code(self, tmp_path):
        """write → parse round-trip 保留 claude-code。"""
        p = tmp_path / "agent.md"
        write_agent_md(
            p,
            name="round",
            prompt="do thing",
            tools=["bash"],
            executor="claude-code",
            retries=4,
        )
        parsed = parse_agent_md(p)
        assert parsed.name == "round"
        assert parsed.executor == "claude-code"
        assert parsed.tools == ["bash"]
        assert parsed.retries == 4
        assert "do thing" in parsed.prompt

    def test_roundtrip_default_stays_default(self, tmp_path):
        """write → parse round-trip 不传 executor，仍是默认。"""
        p = tmp_path / "agent.md"
        write_agent_md(p, name="d", prompt="x")
        parsed = parse_agent_md(p)
        assert parsed.executor == "pydantic-ai"
