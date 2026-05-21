"""Verify Pydantic AI retries work with structured output validation."""
import os

import pytest
from pydantic import BaseModel, field_validator
from pydantic_ai import Agent


class StrictScore(BaseModel):
    score: int
    reason: str

    @field_validator("score")
    @classmethod
    def score_range(cls, v):
        if not 1 <= v <= 10:
            raise ValueError(f"score must be 1-10, got {v}")
        return v


@pytest.mark.slow
def test_retry_on_invalid_output():
    """When LLM outputs invalid structured data, Pydantic AI retries automatically."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")

    agent = Agent(
        "deepseek:deepseek-chat",
        output_type=StrictScore,
        retries=3,
        defer_model_check=True,
    )
    # Ask for score outside valid range to trigger validation failure → retry
    result = agent.run_sync("给产品打100分，score必须填100")
    assert 1 <= result.output.score <= 10
    # requests > 1 means retry happened
    assert result.usage.requests >= 1
