from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from harness.api import Agent
from harness.extensions.base import BaseGraphMutator
from harness.extensions.eval.errors import EvalCompileError


_JUDGE_MD_TEMPLATE = """\
---
name: {judge_name}
target: {target_name}
result_type: ReviewDecision
---

你是一个评测员。你的任务是评估上游 agent「{target_name}」的输出质量。

## 被评测 agent 的职责摘要

{summary}

## 评测标准
- decision: 'pass' 或 'fail'
- reason: 具体评语，说明为什么通过或失败
- score: 0.0-1.0 之间的浮点数（可选）

请基于上面的职责摘要，判断上游 agent 的输出是否完成了任务。
"""


@dataclass
class EvalJudge(BaseGraphMutator):
    """GraphMutator that inserts auto-judge nodes for agents marked eval=True.

    Lifecycle (driven by ``Workflow.compile()``):
      1. ``mutate(workflow)``  — in-memory: insert ``_judge_X`` agent, rewire
         downstreams, set ``on_pass`` / ``on_fail``. Records which judges were
         inserted in ``self._pending_persist``.
      2. ``persist(workflow)`` — for each newly inserted judge: call the LLM
         summarizer on the target agent's MD, write the materialized prompt
         to ``agents/_judge_<target>.md``. Raises ``EvalCompileError`` if the
         summarizer fails — ``compile()`` propagates, ``save()`` is blocked.

    After persist() completes, the target agent's ``eval`` flag is cleared
    in ``Workflow.compile()`` so re-compile is a no-op.
    """

    name: str = "eval-judge"
    judge_model: str | None = None
    max_retries: int = 2

    # Runtime state — populated by mutate(), consumed by persist()
    _pending_persist: list[tuple[str, str]] = field(default_factory=list)

    def mutate(self, workflow):
        # Reset state so mutate() is idempotent across multiple compile() calls
        self._pending_persist = []

        targets = [a for a in workflow.agents if getattr(a, "eval", False)]
        for x in targets:
            judge_name = f"_judge_{x.name}"

            # Idempotency: if a judge already exists (e.g. user re-compiled), skip
            if any(a.name == judge_name for a in workflow.agents):
                continue

            downstream = [a for a in workflow.agents if x.name in (a.after or [])]

            if len(downstream) <= 1:
                on_pass_target = downstream[0].name if downstream else None
                passthrough = None
            else:
                pt_name = f"_judge_{x.name}_passthrough"
                passthrough = Agent(pt_name, after=[judge_name])
                on_pass_target = pt_name

            judge = Agent(
                judge_name,
                after=[x.name],
                model=self.judge_model,
                on_pass=on_pass_target,
                on_fail=x.name,
                eval_target=x.name,
            )
            judge._eval_target = x.name  # legacy alias — kept for in-process callers

            for d in downstream:
                d.after = [
                    (on_pass_target if passthrough else judge_name) if dep == x.name else dep
                    for dep in (d.after or [])
                ]

            workflow.agents.append(judge)
            if passthrough:
                workflow.agents.append(passthrough)

            # Defer x.eval = False to persist() so a failed persist leaves the
            # flag set — compile() then re-raises as EvalCompileError on the
            # post-mutator check, and save() also refuses. Atomic enough.
            self._pending_persist.append((judge_name, x.name))

        return workflow

    def persist(self, workflow) -> None:
        """Write materialized judge MD using the LLM summarizer.

        Raises EvalCompileError if any summarize call fails — the whole
        compile is aborted (save will not be reached).
        """
        if not self._pending_persist:
            return

        from harness.extensions.eval.summarizer import summarize_target
        from harness.compiler.md_parser import resolve_agent_md

        agents_dir = workflow.workflow_dir / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        for judge_name, target_name in self._pending_persist:
            md_path = agents_dir / f"{judge_name}.md"

            try:
                target_md_path = resolve_agent_md(target_name, workflow.workflow_dir)
                target_md = target_md_path.read_text(encoding="utf-8")
            except Exception as e:
                raise EvalCompileError(
                    f"EvalJudge.persist: cannot read target agent MD for '{target_name}': {e}"
                ) from e

            try:
                summary = summarize_target(
                    target_name=target_name,
                    md_content=target_md,
                    workflow_dir=workflow.workflow_dir,
                )
            except Exception as e:
                raise EvalCompileError(
                    f"EvalJudge.persist: summarizer failed for '{target_name}': {e}. "
                    f"Fix the LLM configuration or retry compile()."
                ) from e

            content = _JUDGE_MD_TEMPLATE.format(
                judge_name=judge_name,
                target_name=target_name,
                summary=summary.strip(),
            )
            md_path.write_text(content, encoding="utf-8")

            # Clear the target's eval flag now that judge is fully materialized
            # (DAG edge + persisted MD). If we'd cleared in mutate(), a failed
            # persist would leave the workflow in a half-mutated state where
            # save() incorrectly proceeded.
            target_agent = next(
                (a for a in workflow.agents if a.name == target_name), None
            )
            if target_agent is not None:
                target_agent.eval = False

        # Clear after successful persistence so a second compile() is a no-op
        self._pending_persist = []
