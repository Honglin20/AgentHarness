"""LLM-as-Judge scoring for benchmark tasks."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

_DEFAULT_RUBRIC = """\
Evaluate the agent's output for the given task.

Score each dimension 0-10:
1. Completeness: Does it fully address the task requirements?
2. Accuracy: Is the content correct and free of factual errors?
3. Clarity: Is the response well-organized and easy to understand?

Output ONLY a JSON object: {"score": <0-10>, "reasoning": "<brief explanation>"}
"""

_DEFAULT_MODEL = None  # Falls back to HARNESS_MODEL


class JudgeResult(BaseModel):
    score: float
    reasoning: str


def judge_task(
    task_label: str,
    task_input: dict | str,
    agent_output: str,
    rubric: str | None = None,
    model: str | None = None,
) -> JudgeResult:
    """Score a single task using an LLM judge.

    Args:
        task_label: Human-readable task label.
        task_input: The original task input (dict or string).
        agent_output: The agent's text output.
        rubric: Custom evaluation rubric. Uses default if None.
        model: LLM model override. Uses HARNESS_MODEL if None.

    Returns:
        JudgeResult with score (0-10) and reasoning.
    """
    from harness.engine.llm import LLMClient

    client = LLMClient(model=model) if model else LLMClient()

    input_str = json.dumps(task_input, ensure_ascii=False) if isinstance(task_input, dict) else str(task_input)
    truncated_output = agent_output[:4000] if len(agent_output) > 4000 else agent_output

    prompt = f"""## Task
{task_label}

## Input
{input_str}

## Agent Output
{truncated_output}

## Evaluation Criteria
{rubric or _DEFAULT_RUBRIC}"""

    agent = client.agent(
        system_prompt="You are an objective evaluator. Score the agent's output strictly by the criteria. Output only valid JSON.",
        output_type=str,
        retries=1,
    )
    result = agent.run_sync(prompt)
    return _parse_judge_response(str(result.output))


def _parse_judge_response(text: str) -> JudgeResult:
    """Extract score and reasoning from LLM response."""
    # Try to find JSON in the response
    json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = float(data.get("score", 0))
            score = max(0.0, min(10.0, score))
            return JudgeResult(
                score=round(score / 10, 4),  # Normalize to 0-1
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback: try to extract a number from the response
    num_match = re.search(r'(?:score|rating|grade)[:\s]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if num_match:
        score = float(num_match.group(1))
        score = max(0.0, min(10.0, score))
        return JudgeResult(score=round(score / 10, 4), reasoning=text[:500])

    return JudgeResult(score=0.0, reasoning=f"Failed to parse judge response: {text[:200]}")


async def judge_task_async(
    task_label: str,
    task_input: dict | str,
    agent_output: str,
    rubric: str | None = None,
    model: str | None = None,
) -> JudgeResult:
    """Async version of judge_task."""
    from harness.engine.llm import LLMClient

    client = LLMClient(model=model) if model else LLMClient()

    input_str = json.dumps(task_input, ensure_ascii=False) if isinstance(task_input, dict) else str(task_input)
    truncated_output = agent_output[:4000] if len(agent_output) > 4000 else agent_output

    prompt = f"""## Task
{task_label}

## Input
{input_str}

## Agent Output
{truncated_output}

## Evaluation Criteria
{rubric or _DEFAULT_RUBRIC}"""

    agent = client.agent(
        system_prompt="You are an objective evaluator. Score the agent's output strictly by the criteria. Output only valid JSON.",
        output_type=str,
        retries=1,
    )
    result = await agent.run(prompt)
    parsed = _parse_judge_response(str(result.output))
    await client.aclose()
    return parsed
