"""TranslatorTestBase — shared infrastructure for backend translator tests.

Why this exists:
  Each CLI backend (claude-code / opencode / codex / ...) needs a translator
  that maps its native stream output to harness events. The test scaffolding
  around fixtures, JSONL parsing, and event-type assertions is identical
  across backends. This module captures that shared scaffolding so a new
  backend's test file only declares:
    TRANSLATOR   — the translate() callable under test
    BACKEND_NAME — used to compute fixture paths (sample_<name>_<scenario>.jsonl)
  and then writes test_ methods using the helpers below.

Why ``_base.py`` and not ``conftest.py``:
  conftest.py auto-registers fixtures into the test session, risking name
  collisions with existing fixtures (e.g. ``ctx`` in test_stream_json.py).
  A plain module with an underscore prefix is private, opt-in via import,
  and never auto-collected by pytest.

Why this class is not collected by pytest:
  It defines no ``test_`` methods itself — only helpers. Subclasses write
  the actual tests. Pytest collects per-class test methods, so the base
  class is naturally ignored.

Non-goal:
  This module is test-only. Production code (under ``harness/``) MUST NOT
  import from here — the leading underscore and ``tests/`` location enforce
  that boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from harness.translator import TranslateContext, TranslatedEvent


#: Canonical set of event types a translator is allowed to emit. Asserted
#: by ``assert_event_types_subset`` to catch typos / experimental types
#: leaking through. Mirror of the table in
#: ``docs/refactor/executor-extensibility/backend-integration-template.md``.
#: If you add a new event type to ``harness/translator/<backend>_stream.py``,
#: add it here AND to the template doc.
ALLOWED_EVENT_TYPES: frozenset[str] = frozenset({
    "node.started",
    "node.completed",
    "agent.text_delta",
    "agent.thinking_delta",
    "agent.tool_call",
    "agent.tool_result",
    "agent.api_retry",
    "agent.status_update",
})


class TranslatorTestBase:
    """Shared scaffolding for backend translator tests.

    Subclass + set the two class attributes, then write ``test_*`` methods
    that call the helpers below. Example::

        from harness.translator.opencode_stream import translate
        from tests.translator._base import TranslatorTestBase

        class TestOpencodeTranslator(TranslatorTestBase):
            TRANSLATOR = translate
            BACKEND_NAME = "opencode"

            def test_basic_session(self):
                events = self.load_fixture("basic")
                ctx = TranslateContext(node_id="n", agent_name="a")
                out = self.translate_all(events, ctx)
                self.assert_event_types_subset(out)
    """

    #: Subclass must override — the translate() callable under test.
    TRANSLATOR: Callable[[dict, TranslateContext], list[TranslatedEvent]]

    #: Subclass must override — backend name, used to compute fixture path.
    #: Fixture filename pattern: ``sample_<BACKEND_NAME>_<scenario>.jsonl``
    BACKEND_NAME: str

    # ------------------------------------------------------------------
    # Fixture loading
    # ------------------------------------------------------------------

    @property
    def fixtures_dir(self) -> Path:
        """Path to ``harness/translator/_fixtures/`` (computed from this file)."""
        return (
            Path(__file__).resolve().parent.parent.parent
            / "harness" / "translator" / "_fixtures"
        )

    def fixture_path(self, scenario: str) -> Path:
        """Compute ``sample_<BACKEND_NAME>_<scenario>.jsonl`` path."""
        return self.fixtures_dir / f"sample_{self.BACKEND_NAME}_{scenario}.jsonl"

    def load_fixture(self, scenario: str) -> list[dict]:
        """Load a JSONL fixture as a list of parsed event dicts.

        Skips the test (``pytest.skip``) if the fixture is missing — this
        is intentional: a backend may not have recorded every scenario yet,
        and silent skips are preferable to requiring a full fixture matrix
        before any test can run.

        Blank lines are ignored; each non-blank line must be valid JSON.
        """
        path = self.fixture_path(scenario)
        if not path.exists():
            pytest.skip(f"fixture missing: {path}")
        events: list[dict] = []
        for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                pytest.fail(f"{path}:{lineno}: invalid JSON — {exc}")
        return events

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    def translate_all(
        self,
        events: list[dict],
        ctx: TranslateContext,
    ) -> list[TranslatedEvent]:
        """Translate a sequence of native events, flattening 0..N outputs per input.

        Mirrors the real executor consumption pattern: the executor reads
        one JSONL line at a time and feeds each through ``translate()``,
        accumulating all emitted harness events.
        """
        out: list[TranslatedEvent] = []
        for ev in events:
            out.extend(self.TRANSLATOR(ev, ctx))
        return out

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_event_types_subset(
        self,
        events: list[TranslatedEvent],
        *,
        allowed: frozenset[str] | None = None,
    ) -> None:
        """Assert every emitted event type is in the allowed set.

        Defaults to ``ALLOWED_EVENT_TYPES``. Catches typos and experimental
        types leaking from the translator before they break the frontend
        event router.
        """
        allow = allowed or ALLOWED_EVENT_TYPES
        actual = {e.type for e in events}
        unknown = actual - allow
        assert not unknown, (
            f"{self.BACKEND_NAME} translator emitted event types not in "
            f"allowed set: {sorted(unknown)}. Allowed: {sorted(allow)}. "
            f"If the new type is intentional, extend ALLOWED_EVENT_TYPES "
            f"in tests/translator/_base.py and update "
            f"backend-integration-template.md."
        )

    def assert_tool_call_id_consistency(
        self,
        events: list[TranslatedEvent],
    ) -> None:
        """Assert every ``agent.tool_result`` has a matching ``agent.tool_call``.

        Tool call ↔ result correlation is a harness invariant: the frontend
        matches results to calls by ``tool_call_id``. A result without a
        prior call (or a call without an eventual result) is a translator
        bug, not a backend protocol quirk.

        ``tool_call_id`` missing entirely on either side is also flagged —
        the executor relies on this field for correlation.
        """
        calls_with_id: list[TranslatedEvent] = []
        for e in events:
            if e.type == "agent.tool_call":
                tid = e.payload.get("tool_call_id")
                assert tid, (
                    f"agent.tool_call missing tool_call_id — frontend "
                    f"cannot correlate the eventual result. payload keys: "
                    f"{sorted(e.payload.keys())}"
                )
                calls_with_id.append(e)

        seen_call_ids = {e.payload["tool_call_id"] for e in calls_with_id}
        for e in events:
            if e.type == "agent.tool_result":
                tid = e.payload.get("tool_call_id")
                assert tid, (
                    f"agent.tool_result missing tool_call_id — cannot "
                    f"correlate back to the originating tool_call."
                )
                assert tid in seen_call_ids, (
                    f"agent.tool_result with tool_call_id={tid!r} has no "
                    f"matching agent.tool_call — translator likely dropped "
                    f"or renamed the call event."
                )

    def assert_payload_required_fields(
        self,
        events: list[TranslatedEvent],
        required_per_type: dict[str, tuple[str, ...]],
    ) -> None:
        """Assert each event of a given type carries the required payload keys.

        Example::

            self.assert_payload_required_fields(out, {
                "agent.tool_call": ("tool_name", "tool_call_id", "tool_args"),
                "agent.tool_result": ("tool_call_id", "result"),
            })
        """
        for e in events:
            required = required_per_type.get(e.type)
            if not required:
                continue
            missing = [k for k in required if k not in e.payload]
            assert not missing, (
                f"{e.type} event missing required payload keys "
                f"{missing}. payload keys: {sorted(e.payload.keys())}"
            )
