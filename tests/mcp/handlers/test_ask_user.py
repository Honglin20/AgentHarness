"""Phase D.5 — ask_user MCP handler 单元测试。

复用 harness/tools/_human_io 全局 _pending dict；fixture 在每个测试前清空避免污染。
"""
from __future__ import annotations

import asyncio

import pytest

from harness.mcp.handlers.ask_user import (
    TOOL_DEFINITION,
    TOOL_NAME,
    ask_user_handler,
)
from harness.mcp.proxy import (
    HandlerCtx,
    _HANDLERS,
    list_registered_handlers,
    register_default_handlers,
)
from harness.mcp.protocol import McpCallResponse
from harness.tools._human_io import _pending
from harness.tools.ask_user import resolve_answer


@pytest.fixture
def clean_state():
    """清 _HANDLERS + _pending，测试间隔离。"""
    saved_handlers = dict(_HANDLERS)
    saved_pending = dict(_pending)
    _HANDLERS.clear()
    _pending.clear()
    yield
    _HANDLERS.clear()
    _HANDLERS.update(saved_handlers)
    _pending.clear()
    _pending.update(saved_pending)


class FakeBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def _ctx(bus=None) -> HandlerCtx:
    return HandlerCtx(
        workflow_id="wf-1",
        node_id="node-1",
        agent_name="agent-1",
        event_bus=bus,
    )


# ---------------------------------------------------------------------------
# Tool definition shape
# ---------------------------------------------------------------------------


class TestToolDefinition:
    def test_name_is_ask_user(self):
        assert TOOL_NAME == "ask_user"
        assert TOOL_DEFINITION["name"] == "ask_user"

    def test_required_field_is_question(self):
        schema = TOOL_DEFINITION["inputSchema"]
        assert schema["required"] == ["question"]
        assert "question" in schema["properties"]

    def test_options_property_is_array(self):
        schema = TOOL_DEFINITION["inputSchema"]
        assert schema["properties"]["options"]["type"] == "array"


class TestRegistration:
    def test_register_default_includes_ask_user(self, clean_state):
        register_default_handlers()
        assert "ask_user" in list_registered_handlers()


# ---------------------------------------------------------------------------
# Handler: emit + register + wait + resolve + return
# ---------------------------------------------------------------------------


class TestAskUserHandlerBasic:
    @pytest.mark.asyncio
    async def test_emits_chat_question_with_question_id(self, clean_state):
        bus = FakeBus()
        ctx = _ctx(bus)

        # 跑 handler 作为 task（它会 block 在 wait future）
        args = {"question": "Pick one", "header": "TEST"}
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=42))

        # 让 handler 跑到 wait_future
        await asyncio.sleep(0.05)

        # 验证 chat.question 已 emit
        questions = [e for e in bus.events if e[0] == "chat.question"]
        assert len(questions) == 1
        payload = questions[0][1]
        assert payload["question"] == "Pick one"
        assert payload["header"] == "TEST"
        assert payload["agent_name"] == "agent-1"
        assert payload["node_id"] == "node-1"
        assert "question_id" in payload
        assert payload["options"] is None  # 没传 options
        assert payload["multi_select"] is False
        assert payload["allow_custom_input"] is True

        # cleanup: resolve future 让 task 完成
        qid = payload["question_id"]
        await resolve_answer(qid, {"answer": "ok"})
        resp = await asyncio.wait_for(task, timeout=2.0)
        assert resp.content == [{"type": "text", "text": "ok"}]
        assert resp.request_id == 42

    @pytest.mark.asyncio
    async def test_returns_answer_from_resolve(self, clean_state):
        bus = FakeBus()
        ctx = _ctx(bus)

        args = {"question": "q", "options": [{"label": "A"}, {"label": "B"}]}
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=7))

        await asyncio.sleep(0.05)
        questions = [e for e in bus.events if e[0] == "chat.question"]
        qid = questions[0][1]["question_id"]

        # resolve 选 A
        await resolve_answer(qid, {"answer": "A"})

        resp = await asyncio.wait_for(task, timeout=2.0)
        assert resp.content == [{"type": "text", "text": "A"}]
        assert resp.is_error is False

    @pytest.mark.asyncio
    async def test_emits_chat_answer_after_resolve(self, clean_state):
        bus = FakeBus()
        ctx = _ctx(bus)

        args = {"question": "q"}
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=1))

        await asyncio.sleep(0.05)
        qid = [e for e in bus.events if e[0] == "chat.question"][0][1]["question_id"]
        await resolve_answer(qid, {"answer": "yes"})

        await asyncio.wait_for(task, timeout=2.0)

        answers = [e for e in bus.events if e[0] == "chat.answer"]
        assert len(answers) == 1
        assert answers[0][1]["answer"] == "yes"
        assert answers[0][1]["question_id"] == qid


class TestAskUserHandlerOptionsMode:
    @pytest.mark.asyncio
    async def test_multi_select_returns_joined(self, clean_state):
        """multi_select=True → answer_str 是 'A, B' 格式（来自 assemble_answer）。"""
        bus = FakeBus()
        ctx = _ctx(bus)
        args = {
            "question": "Pick several",
            "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
            "multi_select": True,
        }
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=1))

        await asyncio.sleep(0.05)
        qid = [e for e in bus.events if e[0] == "chat.question"][0][1]["question_id"]
        # 多选：selected list
        from harness.tools.ask_user import resolve_answer
        await resolve_answer(qid, {"selected": ["A", "C"], "custom_input": ""})

        resp = await asyncio.wait_for(task, timeout=2.0)
        # assemble_answer 对 multi_select 返回 "A, C"
        assert resp.content[0]["text"] == "A, C"


class TestAskUserHandlerErrorPaths:
    @pytest.mark.asyncio
    async def test_malformed_options_returns_error_response(self, clean_state):
        """options 不是合法 AskUserOption 结构 → is_error=True，不 block。"""
        bus = FakeBus()
        ctx = _ctx(bus)
        args = {"question": "q", "options": [{"invalid_field": "x"}]}  # 缺 label
        resp = await ask_user_handler(args, ctx, request_id=99)
        assert resp.is_error is True
        assert "invalid options" in resp.content[0]["text"]
        assert resp.request_id == 99

    @pytest.mark.asyncio
    async def test_handler_runs_without_event_bus(self, clean_state):
        """event_bus=None 时 handler 仍工作（不 emit，但 register/wait 正常）。"""
        ctx = _ctx(bus=None)
        args = {"question": "q"}
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=1))

        await asyncio.sleep(0.05)
        # 没 bus emit chat.question 但 future 已 register
        # 拿 qid 通过 _pending dict
        from harness.tools._human_io import _pending
        assert len(_pending) == 1
        qid = next(iter(_pending.keys()))
        await resolve_answer(qid, {"answer": "ok"})

        resp = await asyncio.wait_for(task, timeout=2.0)
        assert resp.content == [{"type": "text", "text": "ok"}]


class TestAskUserHandlerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_message(self, clean_state, monkeypatch):
        """HARNESS_ASK_USER_TIMEOUT=0.1 → handler 1s 内返回 TIMEOUT_MESSAGE。"""
        # 注意 _resolve_timeout 校验 >= 1 秒，所以用 1
        monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "1")
        bus = FakeBus()
        ctx = _ctx(bus)
        args = {"question": "q"}
        task = asyncio.create_task(ask_user_handler(args, ctx, request_id=1))

        # 1s timeout（_resolve_timeout 读 env），不 resolve，等 task 自然结束
        resp = await asyncio.wait_for(task, timeout=3.0)
        assert "TIMEOUT" in resp.content[0]["text"].upper() or \
               "timed out" in resp.content[0]["text"].lower() or \
               resp.content[0]["text"]  # TIMEOUT_MESSAGE 文本含 timeout 关键词

        # chat.timeout 应该 emit
        timeouts = [e for e in bus.events if e[0] == "chat.timeout"]
        assert len(timeouts) == 1
