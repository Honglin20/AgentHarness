"""Verify WS messages are validated, not just json.loads'd.

The old ws_handler.py did `msg = json.loads(raw)` then dispatched on a
raw `msg.get("type")` string. Unknown types were silently ignored,
malformed JSON aborted the connection, and missing required fields were
caught (if at all) deep inside the handler. These tests pin the new
behavior: every inbound message is parsed by `parse_ws_message()`,
which raises `WSValidationError` on any failure.

Wire format note: the production handler nests fields under
`payload` (e.g. `{"type": "chat.answer", "payload": {"question_id": ...}}`).
These schemas validate that real shape — flat-message examples in the
task spec would not match what the frontend actually sends.
"""
import json

import pytest

from server.schemas import (
    WSChatAnswer,
    WSChatFollowup,
    WSProvideGuidance,
    WSStopAndRegenerate,
    WSValidationError,
    parse_ws_message,
)


# ── JSON / structural errors ────────────────────────────────────────────────


def test_parse_malformed_json_rejected():
    with pytest.raises(WSValidationError):
        parse_ws_message("{not valid json")


def test_parse_non_object_rejected():
    """Top-level must be a JSON object, not an array or scalar."""
    with pytest.raises(WSValidationError):
        parse_ws_message('["chat.answer"]')


def test_parse_missing_type_rejected():
    with pytest.raises(WSValidationError):
        parse_ws_message('{"payload": {}}')


def test_parse_unknown_type_rejected():
    with pytest.raises(WSValidationError) as exc:
        parse_ws_message('{"type": "totally.unknown", "payload": {}}')
    msg = str(exc.value).lower()
    assert "unknown" in msg or "invalid" in msg


def test_parse_unknown_type_lists_known_types():
    """Error message lists known types so clients can self-correct."""
    with pytest.raises(WSValidationError) as exc:
        parse_ws_message('{"type": "bogus", "payload": {}}')
    msg = str(exc.value)
    assert "chat.answer" in msg
    assert "chat.followup" in msg


def test_parse_type_wrong_type_rejected():
    """type must be a string, not a number."""
    with pytest.raises(WSValidationError):
        parse_ws_message('{"type": 123, "payload": {}}')


def test_parse_missing_payload_rejected():
    """Every message must carry a payload object."""
    with pytest.raises(WSValidationError) as exc:
        parse_ws_message('{"type": "chat.answer"}')
    assert "payload" in str(exc.value).lower()


# ── chat.answer ─────────────────────────────────────────────────────────────


def test_parse_chat_answer_valid_new_shape():
    """New shape: {question_id, selected: [...], custom_input: '...'}."""
    msg = parse_ws_message(json.dumps({
        "type": "chat.answer",
        "payload": {
            "question_id": "q1",
            "selected": ["a", "b"],
            "custom_input": "extra",
        },
    }))
    assert isinstance(msg, WSChatAnswer)
    assert msg.payload.question_id == "q1"
    assert msg.payload.selected == ["a", "b"]
    assert msg.payload.custom_input == "extra"


def test_parse_chat_answer_valid_legacy_shape():
    """Legacy shape: {question_id, answer: '...'}."""
    msg = parse_ws_message(json.dumps({
        "type": "chat.answer",
        "payload": {"question_id": "q1", "answer": "yes"},
    }))
    assert isinstance(msg, WSChatAnswer)
    assert msg.payload.question_id == "q1"
    assert msg.payload.answer == "yes"


def test_parse_chat_answer_missing_question_id():
    with pytest.raises(WSValidationError) as exc:
        parse_ws_message(json.dumps({
            "type": "chat.answer",
            "payload": {"answer": "yes"},
        }))
    assert "question_id" in str(exc.value).lower()


def test_parse_chat_answer_rejects_non_string_question_id():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "chat.answer",
            "payload": {"question_id": 42, "answer": "x"},
        }))


def test_parse_chat_answer_legacy_shape_preserves_only_sent_keys():
    """Regression: legacy {answer: 'x'} must NOT pick up empty defaults
    for selected/custom_input — downstream assemble_answer() distinguishes
    shapes by field *presence*. A schema that defaults selected=[] and
    custom_input='' would silently drop the answer."""
    msg = parse_ws_message(json.dumps({
        "type": "chat.answer",
        "payload": {"question_id": "q1", "answer": "yes"},
    }))
    raw = msg.payload.model_dump(exclude_unset=True)
    # Only question_id + answer should be present — no selected/custom_input.
    assert set(raw.keys()) == {"question_id", "answer"}
    assert raw["answer"] == "yes"


def test_parse_chat_answer_new_shape_preserves_only_sent_keys():
    """Regression companion: new-shape {selected: [...]} without
    custom_input should NOT include custom_input after exclude_unset."""
    msg = parse_ws_message(json.dumps({
        "type": "chat.answer",
        "payload": {"question_id": "q1", "selected": ["a"]},
    }))
    raw = msg.payload.model_dump(exclude_unset=True)
    assert set(raw.keys()) == {"question_id", "selected"}
    assert raw["selected"] == ["a"]


# ── agent.stop_and_regenerate ──────────────────────────────────────────────


def test_parse_stop_and_regenerate_valid():
    msg = parse_ws_message(json.dumps({
        "type": "agent.stop_and_regenerate",
        "payload": {
            "agent_name": "writer",
            "partial_output": "...",
            "user_guidance": "rewrite",
        },
    }))
    assert isinstance(msg, WSStopAndRegenerate)
    assert msg.payload.agent_name == "writer"
    assert msg.payload.partial_output == "..."
    assert msg.payload.user_guidance == "rewrite"


def test_parse_stop_and_regenerate_defaults_optional_fields():
    msg = parse_ws_message(json.dumps({
        "type": "agent.stop_and_regenerate",
        "payload": {"agent_name": "writer"},
    }))
    assert isinstance(msg, WSStopAndRegenerate)
    assert msg.payload.partial_output == ""
    assert msg.payload.user_guidance == ""


def test_parse_stop_and_regenerate_missing_agent_name():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "agent.stop_and_regenerate",
            "payload": {},
        }))


# ── agent.provide_guidance ─────────────────────────────────────────────────


def test_parse_provide_guidance_valid():
    msg = parse_ws_message(json.dumps({
        "type": "agent.provide_guidance",
        "payload": {"guidance": "use shorter sentences"},
    }))
    assert isinstance(msg, WSProvideGuidance)
    assert msg.payload.guidance == "use shorter sentences"


def test_parse_provide_guidance_missing_field():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "agent.provide_guidance",
            "payload": {},
        }))


def test_parse_provide_guidance_rejects_non_string():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "agent.provide_guidance",
            "payload": {"guidance": 123},
        }))


# ── chat.followup ──────────────────────────────────────────────────────────


def test_parse_chat_followup_valid():
    msg = parse_ws_message(json.dumps({
        "type": "chat.followup",
        "payload": {"agent_name": "writer", "question": "why?"},
    }))
    assert isinstance(msg, WSChatFollowup)
    assert msg.payload.agent_name == "writer"
    assert msg.payload.question == "why?"


def test_parse_chat_followup_missing_question():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "chat.followup",
            "payload": {"agent_name": "writer"},
        }))


def test_parse_chat_followup_missing_agent_name():
    with pytest.raises(WSValidationError):
        parse_ws_message(json.dumps({
            "type": "chat.followup",
            "payload": {"question": "why?"},
        }))
