"""Phase B — stream-json → harness event 翻译器单元测试。

验收锚点（对应 detailed-design.md §5.5）：
  1. 8 类核心事件类型全部翻译正确
  2. 未知事件类型 / 缺字段 → 空列表，不抛
  3. 真实 fixture（claude -p 录制）端到端跑通
  4. token_usage 字段映射符合 harness schema
  5. tool_call ↔ tool_result 通过 tool_call_id 关联
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.translator import TranslateContext, TranslatedEvent, translate
from harness.translator.stream_json import _build_token_usage

FIXTURES = Path(__file__).parent.parent.parent / "harness" / "translator" / "_fixtures"


@pytest.fixture
def ctx() -> TranslateContext:
    return TranslateContext(
        node_id="node-1",
        agent_name="agent-1",
        iteration=3,
        attempt=2,
        model="claude-sonnet-4-6",
    )


# ---------------------------------------------------------------------------
# 各事件类型翻译
# ---------------------------------------------------------------------------


class TestSystemInit:
    def test_system_init_emits_node_started(self, ctx):
        ev = {"type": "system", "subtype": "init", "session_id": "s1", "tools": ["Bash", "Read"]}
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "node.started"
        assert e.payload["node_id"] == "node-1"
        assert e.payload["agent_name"] == "agent-1"
        assert e.payload["attempt"] == 2
        assert e.payload["iteration"] == 3
        # tools 转 ToolBrief 格式
        assert e.payload["tools"] == [
            {"name": "Bash", "description": ""},
            {"name": "Read", "description": ""},
        ]
        assert e.payload["model"] == "claude-sonnet-4-6"

    def test_system_init_without_tools_omits_field(self, ctx):
        ev = {"type": "system", "subtype": "init", "session_id": "s1"}
        out = translate(ev, ctx)
        assert out[0].type == "node.started"
        assert "tools" not in out[0].payload

    def test_system_hook_subtypes_ignored(self, ctx):
        """Hook subtypes are NOT mapped to harness events (hooks are a
        claude-internal concept). status + api_retry DO translate (P2-T4)
        — see TestSystemApiRetry / TestSystemStatus below."""
        for sub in ("hook_started", "hook_response"):
            ev = {"type": "system", "subtype": sub, "session_id": "s"}
            assert translate(ev, ctx) == []


class TestSystemApiRetry:
    """P2-T4: system/api_retry → agent.api_retry — surfaces real-time retry
    progress to the frontend so users do not assume the agent is stuck."""

    def test_api_retry_emits_with_full_payload(self, ctx):
        ev = {
            "type": "system", "subtype": "api_retry",
            "retry_count": 2, "max_retries": 5, "wait_seconds": 1.5,
            "error": "rate limited",
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "agent.api_retry"
        assert e.payload["node_id"] == "node-1"
        assert e.payload["agent_name"] == "agent-1"
        assert e.payload["retry_count"] == 2
        assert e.payload["max_retries"] == 5
        assert e.payload["wait_seconds"] == 1.5
        assert e.payload["error_message"] == "rate limited"

    def test_api_retry_minimal_payload(self, ctx):
        """Only subtype is required; missing fields are omitted (not None)."""
        ev = {"type": "system", "subtype": "api_retry"}
        out = translate(ev, ctx)
        assert len(out) == 1
        assert out[0].type == "agent.api_retry"
        assert "retry_count" not in out[0].payload


class TestSystemStatus:
    """P2-T4: system/status → agent.status_update — surfaces liveness
    (requesting / thinking) so the frontend can show progress during
    long gaps between message deltas."""

    def test_status_emits_with_known_status(self, ctx):
        ev = {"type": "system", "subtype": "status", "status": "thinking"}
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "agent.status_update"
        assert e.payload["status"] == "thinking"
        assert e.payload["node_id"] == "node-1"

    def test_status_with_optional_duration(self, ctx):
        ev = {
            "type": "system", "subtype": "status",
            "status": "requesting", "duration_ms": 250,
        }
        out = translate(ev, ctx)
        assert out[0].payload["duration_ms"] == 250

    def test_status_missing_status_field_defaults_unknown(self, ctx):
        """Defensive: if claude omits the status string, emit 'unknown'
        rather than crashing — sinks can still render the event."""
        ev = {"type": "system", "subtype": "status"}
        out = translate(ev, ctx)
        assert out[0].payload["status"] == "unknown"


class TestStreamEventDelta:
    def test_text_delta_translates_to_text_delta(self, ctx):
        ev = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello"},
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        assert out[0].type == "agent.text_delta"
        assert out[0].payload["text"] == "hello"
        assert out[0].payload["node_id"] == "node-1"
        assert out[0].payload["agent_name"] == "agent-1"

    def test_thinking_delta_translates_to_thinking_delta(self, ctx):
        ev = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "thinking..."},
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        assert out[0].type == "agent.thinking_delta"
        assert out[0].payload["text"] == "thinking..."

    def test_input_json_delta_ignored(self, ctx):
        """partial tool input 不翻译；等最终 tool_use 事件再 emit。"""
        ev = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": "{\"x\":"},
            },
        }
        assert translate(ev, ctx) == []

    def test_empty_text_delta_returns_nothing(self, ctx):
        ev = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": ""},
            },
        }
        assert translate(ev, ctx) == []

    def test_message_lifecycle_events_ignored(self, ctx):
        for inner_type in ("message_start", "message_delta", "message_stop",
                           "content_block_start", "content_block_stop"):
            ev = {"type": "stream_event", "event": {"type": inner_type}}
            assert translate(ev, ctx) == []

    def test_stream_event_with_non_dict_inner_ignored(self, ctx):
        ev = {"type": "stream_event", "event": "garbage"}
        assert translate(ev, ctx) == []


class TestAssistantToolUse:
    def test_assistant_tool_use_emits_tool_call(self, ctx):
        ev = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "call_abc", "name": "Bash",
                     "input": {"command": "echo hi"}},
                ],
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "agent.tool_call"
        assert e.payload["tool_name"] == "Bash"
        assert e.payload["tool_args"] == {"command": "echo hi"}
        assert e.payload["tool_call_id"] == "call_abc"

    def test_assistant_text_block_not_translated(self, ctx):
        """assistant/text 已在 stream_event delta 翻译过；重复会让前端重复渲染。"""
        ev = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "DONE"}]},
        }
        assert translate(ev, ctx) == []

    def test_assistant_thinking_block_not_translated(self, ctx):
        ev = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "..."}]},
        }
        assert translate(ev, ctx) == []

    def test_assistant_multiple_blocks_only_tool_use_emitted(self, ctx):
        ev = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "..."},
                    {"type": "text", "text": "calling..."},
                    {"type": "tool_use", "id": "c1", "name": "Bash", "input": {}},
                    {"type": "tool_use", "id": "c2", "name": "Read", "input": {}},
                ],
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 2
        assert out[0].payload["tool_call_id"] == "c1"
        assert out[1].payload["tool_call_id"] == "c2"


class TestUserToolResult:
    def test_user_tool_result_with_string_content(self, ctx):
        ev = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_abc", "content": "hi"},
                ],
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "agent.tool_result"
        assert e.payload["result"] == "hi"
        assert e.payload["tool_call_id"] == "call_abc"

    def test_user_tool_result_with_list_content(self, ctx):
        ev = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "c1",
                     "content": [
                        {"type": "text", "text": "line1\n"},
                        {"type": "text", "text": "line2"},
                     ]},
                ],
            },
        }
        out = translate(ev, ctx)
        assert out[0].payload["result"] == "line1\nline2"

    def test_user_tool_result_with_none_content(self, ctx):
        ev = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "c1", "content": None},
                ],
            },
        }
        out = translate(ev, ctx)
        assert out[0].payload["result"] == ""

    def test_user_non_tool_result_ignored(self, ctx):
        ev = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "feedback"}]},
        }
        assert translate(ev, ctx) == []


class TestResultEvent:
    def test_result_success_emits_node_completed(self, ctx):
        ev = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 12345,
            "num_turns": 2,
            "result": "DONE",
            "total_cost_usd": 0.042,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 50,
            },
        }
        out = translate(ev, ctx)
        assert len(out) == 1
        e = out[0]
        assert e.type == "node.completed"
        assert e.payload["duration_ms"] == 12345
        assert e.payload["status"] == "success"
        assert e.payload["cost_usd"] == pytest.approx(0.042)
        assert e.payload["token_usage"] == {
            "input": 100, "output": 20, "total": 120, "cache_hit": 50,
        }
        assert e.payload["output_result"] == {"raw": "DONE"}

    def test_result_error_no_longer_emits_node_failed(self, ctx):
        """P2-T4: result.is_error=true MUST NOT emit node.failed from the
        translator. The executor catches is_error via _extract_pre_translate
        and emits agent.executor_error (critical) with full context. The
        translator emitting node.failed here would double-count failures
        on the frontend (ADR Decision 2 emit-uniqueness invariant)."""
        ev = {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "api_error_status": {"status": 429, "message": "rate limited"},
            "duration_ms": 1000,
        }
        out = translate(ev, ctx)
        assert out == [], (
            "translator must not emit on result.is_error — executor owns "
            "agent.executor_error emit (P2-T3) to preserve emit-uniqueness"
        )

    def test_result_without_usage_still_emits_completed(self, ctx):
        ev = {"type": "result", "is_error": False, "duration_ms": 100}
        out = translate(ev, ctx)
        assert out[0].type == "node.completed"
        assert "token_usage" not in out[0].payload


# ---------------------------------------------------------------------------
# 防御性 / 边界
# ---------------------------------------------------------------------------


class TestTaskCreateTranslation:
    """claude 2.1.150+ builtin TaskCreate/TaskUpdate → harness todo 翻译。

    claude deprecated 了 TodoWrite，改用 TaskCreate/TaskUpdate 做 plan
    tracking。translator 在两个阶段翻译：
      - tool_result（user message）：解析 "Task #N created successfully:
        SUBJECT" → emit todo.created（task_id 来自 claude 分配的数字）
      - tool_use（assistant message）：TaskUpdate input {taskId, status} →
        emit todo.updated（task_id 直接用 taskId，跟 created 一致）

    前端 handleTodoCreated 是增量的（按 task_id 去重），所以每次 TaskCreate
    emit 一个 items=[单步] 的 todo.created 是安全的。
    """

    def _taskcreate_result_event(self, task_num, subject, tool_use_id="r1"):
        return {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_use_id,
                     "content": f"Task #{task_num} created successfully: {subject}"},
                ],
            },
        }

    def _taskupdate_use_event(self, task_id, status, call_id="u1"):
        return {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": call_id, "name": "TaskUpdate",
                     "input": {"taskId": task_id, "status": status}},
                ],
            },
        }

    def test_taskcreate_result_emits_todo_created(self, ctx):
        out = translate(self._taskcreate_result_event(1, "Gather reqs"), ctx)
        assert [e.type for e in out] == ["agent.tool_result", "todo.created"]

    def test_taskcreate_result_preserves_tool_result(self, ctx):
        out = translate(self._taskcreate_result_event(1, "Gather reqs"), ctx)
        tr = out[0]
        assert tr.payload["tool_call_id"] == "r1"
        assert "Task #1 created" in tr.payload["result"]

    def test_taskcreate_result_maps_all_fields(self, ctx):
        out = translate(self._taskcreate_result_event(42, "Step A"), ctx)
        created = out[1]
        assert created.payload["node_id"] == "node-1"
        assert created.payload["agent_name"] == "agent-1"
        items = created.payload["items"]
        assert len(items) == 1
        # task_id 直接用 claude 分配的数字字符串（让 TaskUpdate 能匹配）
        assert items[0]["task_id"] == "42"
        assert items[0]["content"] == "Step A"
        # activeForm 在 input 里，result 拿不到 → fallback 到 content
        assert items[0]["activeForm"] == "Step A"
        assert items[0]["status"] == "pending"  # TaskCreate 默认 pending

    def test_taskcreate_result_id_matches_taskupdate(self, ctx):
        """关键不变量：TaskCreate 的 task_id 必须跟后续 TaskUpdate.taskId
        一致，否则前端 todo.updated 找不到对应 step，状态无法更新。"""
        created = translate(self._taskcreate_result_event(1, "X"), ctx)[1]
        updated = translate(self._taskupdate_use_event("1", "completed"), ctx)[1]
        assert created.payload["items"][0]["task_id"] == updated.payload["task_id"]

    def test_taskcreate_result_non_matching_text_no_emit(self, ctx):
        """非 TaskCreate 的 result 不触发翻译。"""
        ev = {
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r1",
                 "content": "ls: 5 files found"},
            ]},
        }
        out = translate(ev, ctx)
        assert [e.type for e in out] == ["agent.tool_result"]

    def test_taskupdate_emits_todo_updated_after_tool_call(self, ctx):
        out = translate(self._taskupdate_use_event("1", "completed"), ctx)
        assert [e.type for e in out] == ["agent.tool_call", "todo.updated"]

    def test_taskupdate_maps_status(self, ctx):
        for claude_status, expected in [
            ("in_progress", "in_progress"),
            ("completed", "completed"),
            ("pending", "pending"),
            # claude 用 cancelled，harness 用 skipped
            ("cancelled", "skipped"),
            # 未知 status fallback 到 pending
            ("weird", "pending"),
        ]:
            out = translate(self._taskupdate_use_event("1", claude_status), ctx)
            updated = out[-1]
            assert updated.type == "todo.updated"
            assert updated.payload["status"] == expected, f"{claude_status} → {expected}"

    def test_taskupdate_missing_taskid_no_emit(self, ctx):
        """TaskUpdate 没 taskId 时不 emit（无法关联到 step）。"""
        ev = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "TaskUpdate",
                 "input": {"status": "completed"}},  # 缺 taskId
            ]},
        }
        out = translate(ev, ctx)
        assert [e.type for e in out] == ["agent.tool_call"]

    def test_non_taskupdate_tool_no_translation(self, ctx):
        """非 TaskUpdate 的 tool_use 不触发 todo 翻译。"""
        ev = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "c1", "name": "Bash",
                 "input": {"command": "ls"}},
            ]},
        }
        out = translate(ev, ctx)
        assert [e.type for e in out] == ["agent.tool_call"]

    def test_e2e_create_then_update_workflow(self, ctx):
        """端到端：TaskCreate result → todo.created, TaskUpdate use → todo.updated。
        验证 task_id 链路完整，前端能正确渲染 status 流转。"""
        out = []
        # 模型调 TaskCreate(subject="A")
        out.extend(translate(self._taskcreate_result_event(1, "Task A"), ctx))
        # 模型调 TaskCreate(subject="B")
        out.extend(translate(self._taskcreate_result_event(2, "Task B"), ctx))
        # 模型调 TaskUpdate(taskId="1", status="in_progress")
        out.extend(translate(self._taskupdate_use_event("1", "in_progress"), ctx))
        # 模型调 TaskUpdate(taskId="1", status="completed")
        out.extend(translate(self._taskupdate_use_event("1", "completed"), ctx))
        # 模型调 TaskUpdate(taskId="2", status="in_progress")
        out.extend(translate(self._taskupdate_use_event("2", "in_progress"), ctx))

        todo_events = [e for e in out if e.type.startswith("todo.")]
        # 2 created + 3 updated
        assert len(todo_events) == 5
        # 第一个 created 是 Task A, task_id="1"
        assert todo_events[0].payload["items"][0]["task_id"] == "1"
        assert todo_events[0].payload["items"][0]["content"] == "Task A"
        # 第二个 created 是 Task B, task_id="2"
        assert todo_events[1].payload["items"][0]["task_id"] == "2"
        # 后续 3 个 updated 都正确指向 task_id
        assert todo_events[2].payload["task_id"] == "1"
        assert todo_events[2].payload["status"] == "in_progress"
        assert todo_events[3].payload["status"] == "completed"
        assert todo_events[4].payload["task_id"] == "2"


class TestDefensiveParsing:
    def test_non_dict_input_returns_empty(self, ctx):
        assert translate(None, ctx) == []  # type: ignore[arg-type]
        assert translate("not a dict", ctx) == []  # type: ignore[arg-type]
        assert translate([], ctx) == []  # type: ignore[arg-type]

    def test_unknown_event_type_returns_empty(self, ctx):
        """未知事件不抛、不 warn（warn 级别只在 debug log，CI 不噪音）。"""
        ev = {"type": "future_event_type", "payload": "whatever"}
        assert translate(ev, ctx) == []

    def test_missing_type_field_returns_empty(self, ctx):
        assert translate({"no_type": "here"}, ctx) == []

    def test_missing_inner_event_field_returns_empty(self, ctx):
        ev = {"type": "stream_event"}  # 无 event 字段
        assert translate(ev, ctx) == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestBuildTokenUsage:
    def test_full_usage(self):
        u = _build_token_usage({
            "input_tokens": 100, "output_tokens": 50,
            "cache_read_input_tokens": 30, "reasoning_tokens": 10,
        })
        assert u == {"input": 100, "output": 50, "total": 150,
                     "cache_hit": 30, "reasoning": 10}

    def test_empty_usage_returns_none(self):
        assert _build_token_usage({}) is None
        assert _build_token_usage(None) is None

    def test_partial_usage(self):
        u = _build_token_usage({"input_tokens": 100, "output_tokens": 0})
        assert u == {"input": 100, "output": 0, "total": 100}

    def test_corrupted_usage_returns_none(self, ctx):
        """corrupted usage 不抛、返回 None 让翻译继续。"""
        assert _build_token_usage({"input_tokens": "not_a_number"}) is None


# ---------------------------------------------------------------------------
# Fixture-driven end-to-end
# ---------------------------------------------------------------------------


class TestRealFixtureE2E:
    """用 Phase B 录制的真实 claude -p 输出跑翻译器，确保对真实 stream-json 工作。"""

    @pytest.fixture
    def sample_events(self, ctx):
        path = FIXTURES / "sample_with_bash.jsonl"
        if not path.exists():
            pytest.skip(f"fixture missing: {path}")
        raw = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        out: list[TranslatedEvent] = []
        for line in raw:
            out.extend(translate(line, ctx))
        return out

    def test_produces_expected_event_types(self, sample_events):
        types = {e.type for e in sample_events}
        assert "node.started" in types
        assert "node.completed" in types
        assert "agent.tool_call" in types
        assert "agent.tool_result" in types

    def test_tool_call_and_result_share_id(self, sample_events):
        calls = [e for e in sample_events if e.type == "agent.tool_call"]
        results = [e for e in sample_events if e.type == "agent.tool_result"]
        assert len(calls) >= 1
        assert len(results) >= 1
        # tool_result 必须有对应的 tool_call_id
        call_ids = {c.payload["tool_call_id"] for c in calls}
        for r in results:
            assert r.payload["tool_call_id"] in call_ids, (
                f"tool_result {r.payload['tool_call_id']} has no matching tool_call"
            )

    def test_node_started_carries_tools_list(self, sample_events):
        starts = [e for e in sample_events if e.type == "node.started"]
        assert len(starts) == 1
        tools = starts[0].payload.get("tools", [])
        tool_names = {t["name"] for t in tools}
        assert "Bash" in tool_names

    def test_node_completed_carries_cost_and_usage(self, sample_events):
        completed = [e for e in sample_events if e.type == "node.completed"]
        assert len(completed) == 1
        p = completed[0].payload
        assert p["status"] == "success"
        assert p["duration_ms"] > 0
        assert p["cost_usd"] > 0
        assert p["token_usage"]["total"] > 0
        assert p["token_usage"]["input"] > 0
        assert p["token_usage"]["output"] > 0
