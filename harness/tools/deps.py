from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from harness.engine.token_aggregator import TokenAggregator


class AgentDeps(BaseModel):
    """通过 RunContext.deps 传递给工具的运行时上下文

    Tools and the dynamic system-prompt function (runtime_status) both read
    this same instance within one agent iter() run. Tools may MUTATE
    ``last_tool_failure`` to surface failures to the next model request;
    runtime_status reads it to inject a runtime-status reminder. This shared-
    mutable-instance contract is what makes the dynamic layer work without a
    separate side-channel.
    """
    model_config = ConfigDict(
        extra="allow",
        # TokenAggregator is a plain (non-pydantic) class — pydantic v2 needs
        # this to accept arbitrary types as field values.
        arbitrary_types_allowed=True,
    )

    workdir: str = "."
    agent_name: str = ""
    depth: int = 0
    workflow_id: str = ""
    node_id: str = ""
    # Loop iteration counter for this node invocation (1-indexed). Injected
    # by node_factory at deps construction time. Consumed by todo tool to
    # stamp StepEntry.iteration. Plan F.
    iteration: int = 1
    # Runtime-only: never serialized (carries mutable aggregator state that
    # makes no sense to persist or send over the wire).
    token_aggregator: TokenAggregator | None = Field(default=None, exclude=True)
    # Most recent tool failure observed during this iter() run, written by
    # tools on their exception paths and read by the runtime_status dynamic
    # system-prompt function to nudge the model. Cleared (set to None) by
    # runtime_status after it surfaces the failure, so a stale error does not
    # haunt every subsequent request. Runtime-only — never serialized.
    last_tool_failure: dict[str, Any] | None = Field(default=None, exclude=True)
    # Generic one-shot reminder queue (TASK 6 of the refinement plan). Any
    # module that observes a transient condition worth surfacing (file changed
    # since last read, duplicate tool call, ...) appends a short string here;
    # runtime_status flushes the queue each turn into a <runtime-status>
    # Reminders block, then clears it. Unlike last_tool_failure (structured:
    # tool/error/hint), this is free-text and open-ended — the OCP channel for
    # ad-hoc reminders that don't warrant their own field. Runtime-only.
    pending_reminders: list[str] = Field(default_factory=list, exclude=True)
