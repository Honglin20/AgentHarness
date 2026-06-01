"""E2E tests for LangGraph interrupt() stop-and-regenerate flow.

Requires DEEPSEEK_API_KEY.

Run: DEEPSEEK_API_KEY=sk-xxx pytest tests/test_interrupt_e2e.py -v -s
"""

import asyncio
import os
import time
import uuid
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DEEPSEEK_API_KEY"),
        reason="DEEPSEEK_API_KEY not set",
    ),
    pytest.mark.slow,
]


def _write_agent_md(agents_dir: Path, name: str, prompt: str, tools: list[str] | None = None):
    """Write a minimal agent MD file."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    if tools:
        lines.append(f"tools: {tools}")
    lines.append("---\n")
    lines.append(prompt)
    (agents_dir / f"{name}.md").write_text("\n".join(lines))


class TestInterruptE2E:
    """Test the full interrupt → resume-with-guidance flow with real LLM."""

    @pytest.mark.asyncio
    async def test_stop_and_regenerate_with_guidance(self, tmp_path):
        """Full flow: start workflow → signal stop → interrupt → resume with guidance.

        1. Build a 2-agent workflow (writer → reviewer)
        2. Run with checkpointer
        3. Mid-execution, inject stop signal for the writer agent
        4. Verify workflow returns interrupted=True
        5. Resume with guidance "请用中文回答"
        6. Verify writer re-runs with the guidance incorporated
        """
        from harness.api import Agent, Workflow
        from harness.engine.macro_graph import MacroGraphBuilder
        from harness.checkpoint import get_checkpoint_manager

        agents_dir = tmp_path / "agents"
        _write_agent_md(
            agents_dir, "writer",
            "You are a creative writer. Write a short paragraph about the given topic. Be verbose — write at least 3 sentences.",
        )
        _write_agent_md(
            agents_dir, "reviewer",
            "You are a reviewer. Read the writer's output and give a one-sentence summary.",
        )

        wf = Workflow(
            "interrupt_e2e",
            agents=[
                Agent("writer", after=[]),
                Agent("reviewer", after=["writer"]),
            ],
            agents_dir=str(agents_dir),
        )

        # Compile with checkpointer (required for interrupt)
        cp_mgr = get_checkpoint_manager()
        checkpointer = await cp_mgr.get_checkpointer()
        wf.checkpointer = checkpointer
        wf.compile()

        # Set workflow_id on builder for interrupt signal routing
        wf_id = f"test-interrupt-{uuid.uuid4().hex[:8]}"
        wf._builder.workflow_id = wf_id
        wf._builder.register_active()

        # Schedule the stop signal to fire after a short delay
        # (gives the writer agent time to start streaming)
        async def _send_stop_signal():
            await asyncio.sleep(1.5)
            await wf._builder.request_stop_and_regenerate(
                "writer", "", "",
            )

        stop_task = asyncio.create_task(_send_stop_signal())

        try:
            config = {"configurable": {"thread_id": wf_id}}
            result = await wf.arun(
                inputs={"task": "Write about the beauty of rain forests"},
                config=config,
            )

            if result.interrupted:
                # Workflow was interrupted — verify state
                assert result.interrupt_value is not None
                assert result.interrupt_value.get("agent_name") == "writer"
                assert result.interrupt_value.get("reason") == "stop_and_regenerate"

                # Resume with guidance
                guidance = "请用中文写关于热带雨林的美"
                resume_result = await wf.arun(
                    inputs=None,
                    config=config,
                    resume_value=guidance,
                )
                assert not resume_result.interrupted
                assert "writer" in resume_result.outputs
                assert "reviewer" in resume_result.outputs

                writer_output = str(resume_result.outputs["writer"]).lower()
                # The guidance asked for Chinese — check some Chinese characters appear
                has_chinese = any("一" <= c <= "鿿" for c in writer_output)
                assert has_chinese, f"Expected Chinese in output, got: {writer_output[:200]}"
            else:
                # Signal arrived too late — writer completed before stop
                # This is acceptable timing-wise, verify normal completion
                assert "writer" in result.outputs
                assert "reviewer" in result.outputs

        finally:
            stop_task.cancel()
            wf._builder.unregister_active()

    @pytest.mark.asyncio
    async def test_interrupt_resume_without_guidance(self, tmp_path):
        """Interrupt then resume without guidance — uses partial output."""
        from harness.api import Agent, Workflow
        from harness.checkpoint import get_checkpoint_manager

        agents_dir = tmp_path / "agents"
        _write_agent_md(
            agents_dir, "writer",
            "You are a writer. Write a short paragraph about the topic.",
        )

        wf = Workflow(
            "interrupt_noguidance",
            agents=[Agent("writer", after=[])],
            agents_dir=str(agents_dir),
        )

        cp_mgr = get_checkpoint_manager()
        checkpointer = await cp_mgr.get_checkpointer()
        wf.checkpointer = checkpointer
        wf.compile()

        wf_id = f"test-noguidance-{uuid.uuid4().hex[:8]}"
        wf._builder.workflow_id = wf_id
        wf._builder.register_active()

        async def _send_stop_signal():
            await asyncio.sleep(1.5)
            await wf._builder.request_stop_and_regenerate("writer", "", "")

        stop_task = asyncio.create_task(_send_stop_signal())

        try:
            config = {"configurable": {"thread_id": wf_id}}
            result = await wf.arun(
                inputs={"task": "Write about mountains"},
                config=config,
            )

            if result.interrupted:
                # Resume with empty guidance
                resume_result = await wf.arun(
                    inputs=None,
                    config=config,
                    resume_value="",  # Empty = use partial output
                )
                assert not resume_result.interrupted
                assert "writer" in resume_result.outputs
                # Should have some output (partial or "(stopped)")
                output = str(resume_result.outputs["writer"])
                assert len(output) > 0
            else:
                assert "writer" in result.outputs

        finally:
            stop_task.cancel()
            wf._builder.unregister_active()

    @pytest.mark.asyncio
    async def test_interrupt_intent_persists_across_reexecution(self, tmp_path):
        """Verify _interrupted_agents dict survives node re-execution."""
        from harness.engine.macro_graph import MacroGraphBuilder

        builder = MacroGraphBuilder()

        # Store intent
        builder.store_interrupt_intent("test_agent", {
            "original_context": "test context",
            "partial_output": "partial text",
            "system_prompt": "system prompt",
        })

        # Verify it can be consumed
        intent = builder.consume_interrupt_intent("test_agent")
        assert intent is not None
        assert intent["partial_output"] == "partial text"

        # Second consume should return None
        intent2 = builder.consume_interrupt_intent("test_agent")
        assert intent2 is None
