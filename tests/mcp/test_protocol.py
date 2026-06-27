"""Phase D.1 — IPC protocol 消息序列化单元测试。"""
from __future__ import annotations

import json

import pytest

from harness.mcp.protocol import (
    PROTOCOL_VERSION,
    McpCallRequest,
    McpCallResponse,
    McpError,
)


class TestProtocolVersion:
    def test_protocol_version_is_2024_11_05(self):
        """claude 2.1.150 实测接受的版本（Phase 1 V3 验证）。"""
        assert PROTOCOL_VERSION == "2024-11-05"


class TestMcpCallRequest:
    def test_roundtrip_with_arguments(self):
        req = McpCallRequest(request_id=42, tool_name="ping", arguments={"text": "hi"})
        line = req.to_json_line()
        assert "\"kind\":\"call_request\"" in line or "\"kind\": \"call_request\"" in line
        restored = McpCallRequest.from_json_line(line)
        assert restored.request_id == 42
        assert restored.tool_name == "ping"
        assert restored.arguments == {"text": "hi"}

    def test_roundtrip_without_arguments_defaults_to_empty_dict(self):
        req = McpCallRequest(request_id=1, tool_name="noop")
        line = req.to_json_line()
        restored = McpCallRequest.from_json_line(line)
        assert restored.arguments == {}

    def test_from_malformed_kind_raises(self):
        bad = json.dumps({"kind": "wrong_kind", "request_id": 1, "tool_name": "x"})
        with pytest.raises(AssertionError, match=r"expected call_request"):
            McpCallRequest.from_json_line(bad)

    def test_to_json_line_is_single_line_no_newline_inside(self):
        req = McpCallRequest(request_id=1, tool_name="x", arguments={"a": "b\nc"})
        line = req.to_json_line()
        assert "\n" not in line  # 字符串内的 \n 已被 JSON 编码为 \\n
        assert line.endswith("}")  # 单行 JSON


class TestMcpCallResponse:
    def test_roundtrip_text_content(self):
        resp = McpCallResponse.text(99, "pong")
        line = resp.to_json_line()
        restored = McpCallResponse.from_json_line(line)
        assert restored.request_id == 99
        assert restored.is_error is False
        assert restored.content == [{"type": "text", "text": "pong"}]

    def test_roundtrip_error_flag(self):
        resp = McpCallResponse.text(1, "boom", is_error=True)
        restored = McpCallResponse.from_json_line(resp.to_json_line())
        assert restored.is_error is True

    def test_roundtrip_complex_content(self):
        resp = McpCallResponse(
            request_id=7,
            content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
        )
        restored = McpCallResponse.from_json_line(resp.to_json_line())
        assert len(restored.content) == 2

    def test_from_malformed_kind_raises(self):
        bad = json.dumps({"kind": "wrong", "request_id": 1, "content": []})
        with pytest.raises(AssertionError, match=r"expected call_response"):
            McpCallResponse.from_json_line(bad)


class TestMcpError:
    def test_serialization(self):
        err = McpError(request_id=1, code=-32601, message="not found")
        line = err.to_json_line()
        d = json.loads(line)
        assert d["kind"] == "error"
        assert d["code"] == -32601
        assert d["message"] == "not found"
