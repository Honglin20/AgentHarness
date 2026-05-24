from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from harness.api import Agent
from harness.extensions.base import BaseGraphMutator


_JUDGE_MD_TEMPLATE = """\
---
name: {judge_name}
target: {target_name}
result_type: ReviewDecision
---

你是一个评测员。你的任务是评估上游 agent「{target_name}」的输出质量。

## 评测标准
- decision: 'pass' 或 'fail'
- reason: 具体评语，说明为什么通过或失败
- score: 0.0-1.0 之间的浮点数（可选）

请根据上游 agent 的任务描述和实际输出，判断其是否完成了任务。
"""


@dataclass
class EvalJudge(BaseGraphMutator):
    """GraphMutator that inserts auto-judge nodes for agents marked eval=True.

    For each eval=True agent X:
      - Create _judge_X (after=[X], on_fail=X, on_pass=<downstream>)
      - Rewire X's downstreams to depend on _judge_X instead of X
      - Multiple downstreams get a _judge_X_passthrough fan-out node
    """

    name: str = "eval-judge"
    judge_model: str | None = None
    max_retries: int = 2

    def mutate(self, workflow):
        targets = [a for a in workflow.agents if getattr(a, "eval", False)]
        for x in targets:
            judge_name = f"_judge_{x.name}"
            downstream = [a for a in workflow.agents if x.name in a.after]

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
            )
            judge._eval_target = x.name  # runtime marker

            for d in downstream:
                d.after = [
                    (on_pass_target if passthrough else judge_name) if dep == x.name else dep
                    for dep in d.after
                ]

            workflow.agents.append(judge)
            if passthrough:
                workflow.agents.append(passthrough)

            # Auto-generate judge MD if it doesn't exist
            self._ensure_judge_md(workflow, judge_name, x.name)

        return workflow

    def _ensure_judge_md(self, workflow, judge_name: str, target_name: str) -> None:
        """Write _judge_X.md to workflow's agents dir if it doesn't exist yet."""
        agents_dir = workflow.workflow_dir / "agents"
        md_path = agents_dir / f"{judge_name}.md"
        if md_path.exists():
            return
        md_path.parent.mkdir(parents=True, exist_ok=True)
        content = _JUDGE_MD_TEMPLATE.format(
            judge_name=judge_name,
            target_name=target_name,
        )
        md_path.write_text(content, encoding="utf-8")
