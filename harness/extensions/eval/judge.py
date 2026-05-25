from __future__ import annotations

from dataclasses import dataclass, field

from harness.api import Agent
from harness.extensions.base import BaseGraphMutator


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

        return workflow
