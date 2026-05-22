from pydantic import BaseModel
from typing import Literal


class ReviewDecision(BaseModel):
    decision: Literal["pass", "fail"]
    reason: str
    score: float | None = None
