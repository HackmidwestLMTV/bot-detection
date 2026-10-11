"""Typed model reports matching the shared RoundReport contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoundReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round: int = Field(ge=1)
    agent: Literal["red", "blue"]
    attempts: int = Field(ge=0)
    passed: int = Field(ge=0)
    best_params: dict[str, float]
    what_changed: str
    evidence: list[str]

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.passed > self.attempts:
            raise ValueError("passed cannot exceed attempts")
        return self
