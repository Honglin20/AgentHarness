"""Phase A — Agent 类的 executor 字段单元测试。

验收锚点（对应 detailed-design.md §4.3）：
  1. 默认值 = ``"pydantic-ai"``
  2. ``to_dict()`` 仅在非默认值时写入 executor 字段（保持旧 workflow.json 零变化）
  3. ``from_dict()`` 缺省时填默认值
  4. 白名单校验 fail-loud
"""
from __future__ import annotations

import pytest

from harness.core.agent import (
    BUILTIN_EXECUTORS,
    DEFAULT_EXECUTOR,
    VALID_EXECUTORS,
    Agent,
)


class TestExecutorFieldDefault:
    def test_default_is_pydantic_ai(self):
        assert DEFAULT_EXECUTOR == "pydantic-ai"
        a = Agent("x")
        assert a.executor == "pydantic-ai"

    def test_valid_executors_whitelist_includes_both_backends(self):
        # P3-T5: VALID_EXECUTORS is now a function (dynamic — builtin +
        # profile registry). BUILTIN_EXECUTORS is the static set.
        valid = VALID_EXECUTORS()
        assert "pydantic-ai" in valid
        assert "claude-code" in valid
        assert len(valid) >= 2

    def test_valid_executors_includes_registered_profiles(self):
        """P3-T5: registering a profile adds it to the valid set."""
        from harness.engine.cli_profile import (
            CliProfile, register_cli_profile, reset_registry,
        )
        # Fixture: reset + reload builtins so test isolation holds
        reset_registry()
        try:
            from harness.cli_profiles import load_builtin_profiles
            load_builtin_profiles()
            custom_profile = CliProfile(
                name="mock-opencode", prompt_paradigm="minimal",
                cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
                flags=(), prompt_channel="stdin", mcp_flag_template=None,
                env_overlay_prefixes=("X",),
                translator=lambda r, c: [], result_extractor=lambda t, rt: t,
            )
            register_cli_profile(custom_profile)
            assert "mock-opencode" in VALID_EXECUTORS()
            # Agent construction with the new executor succeeds
            agent = Agent("x", executor="mock-opencode")
            assert agent.executor == "mock-opencode"
        finally:
            reset_registry()


class TestExecutorFieldAssignment:
    def test_explicit_pydantic_ai(self):
        a = Agent("x", executor="pydantic-ai")
        assert a.executor == "pydantic-ai"

    def test_explicit_claude_code(self):
        a = Agent("x", executor="claude-code")
        assert a.executor == "claude-code"

    def test_invalid_value_raises_value_error(self):
        with pytest.raises(ValueError, match=r"executor must be one of"):
            Agent("x", executor="bogus")

    def test_invalid_value_error_message_lists_valid_options(self):
        with pytest.raises(ValueError) as exc:
            Agent("x", executor="custom-thing")
        msg = str(exc.value)
        assert "pydantic-ai" in msg
        assert "claude-code" in msg


class TestExecutorFieldSerialization:
    def test_to_dict_omits_default_executor(self):
        """默认值不写入 workflow.json —— 旧文件零变化。"""
        a = Agent("x")
        d = a.to_dict()
        assert "executor" not in d, (
            "default executor must NOT be serialized — keeps workflow.json diffs minimal"
        )

    def test_to_dict_includes_non_default_executor(self):
        a = Agent("x", executor="claude-code")
        d = a.to_dict()
        assert d.get("executor") == "claude-code"

    def test_from_dict_default_when_field_absent(self):
        """旧 workflow.json（无 executor 字段）加载后默认 pydantic-ai。"""
        a = Agent.from_dict({"name": "old"})
        assert a.executor == "pydantic-ai"

    def test_from_dict_preserves_explicit_claude_code(self):
        a = Agent.from_dict({"name": "x", "executor": "claude-code"})
        assert a.executor == "claude-code"

    def test_from_dict_preserves_explicit_pydantic_ai(self):
        a = Agent.from_dict({"name": "x", "executor": "pydantic-ai"})
        assert a.executor == "pydantic-ai"

    def test_from_dict_rejects_invalid_executor(self):
        """loader 入口也要 fail-loud —— 防止手工编辑的 workflow.json 含错值静默通过。"""
        with pytest.raises(ValueError):
            Agent.from_dict({"name": "x", "executor": "invalid"})


class TestExecutorFieldRoundTrip:
    def test_roundtrip_claude_code(self):
        original = Agent("cc", executor="claude-code", retries=5)
        d = original.to_dict()
        assert d["executor"] == "claude-code"
        restored = Agent.from_dict(d)
        assert restored.executor == "claude-code"
        assert restored.retries == 5

    def test_roundtrip_default_omits_field_on_both_ends(self):
        original = Agent("d")
        d = original.to_dict()
        assert "executor" not in d
        restored = Agent.from_dict(d)
        assert restored.executor == "pydantic-ai"

    def test_roundtrip_preserves_other_fields(self):
        """executor 字段不能干扰其他字段的序列化。"""
        original = Agent(
            "x",
            executor="claude-code",
            after=["dep1"],
            tools=["bash"],
            model="claude-sonnet-4-6",
            retries=7,
        )
        d = original.to_dict()
        restored = Agent.from_dict(d)
        assert restored.name == "x"
        assert restored.after == ["dep1"]
        assert restored.tools == ["bash"]
        assert restored.model == "claude-sonnet-4-6"
        assert restored.retries == 7
        assert restored.executor == "claude-code"
