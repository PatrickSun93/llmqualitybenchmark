"""Pydantic models for task specifications.

A task specifies an open-ended idea given to the arm, plus hidden ground-truth
context (canon) used by the User Simulator, plus annotations used by deterministic
quality checks (critical decisions, key ambiguities).
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class TaskCanon(BaseModel):
    """Hidden facts the simulated user 'has in their head'.

    Visible only to the User Simulator. Arms must elicit these via Q&A.
    Free-form keys; documented examples in tasks/*.yaml.
    """

    target_user: str | None = None
    platform: str | None = None
    business_model: str | None = None
    key_dislike: str | None = None
    constraint_tech: str | None = None
    constraint_budget: str | None = None
    out_of_scope: str | None = None

    extra: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    def as_prompt_block(self) -> str:
        """Render the canon as text for the simulator's system prompt."""
        items = self.model_dump(exclude={"extra"}, exclude_none=True)
        items.update(self.extra)
        if not items:
            return "(canon is empty)"
        return "\n".join(f"- {k}: {v}" for k, v in items.items())


class Task(BaseModel):
    """One benchmark task."""

    id: str
    idea: str = Field(..., description="The open-ended prompt given to each arm.")
    canon: TaskCanon
    must_be_addressed: list[str] = Field(
        default_factory=list,
        description="Critical decision points any reasonable design must commit to.",
    )
    key_ambiguities: list[str] = Field(
        default_factory=list,
        description="Things the design system should ideally surface as questions.",
    )
    canon_silent_on: list[str] = Field(
        default_factory=list,
        description="Things the simulator should give a non-answer to (canon doesn't cover).",
    )

    @field_validator("idea")
    @classmethod
    def _idea_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("idea must be non-empty")
        return v

    @classmethod
    def from_yaml(cls, path: Path) -> Task:
        with path.open() as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)


def load_tasks(source: Path) -> list[Task]:
    """Load one task or every *.yaml task in a directory."""
    if source.is_file():
        return [Task.from_yaml(source)]
    return [Task.from_yaml(p) for p in sorted(source.glob("*.yaml"))]
