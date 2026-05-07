"""Common types for arm adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..schema import Task
from ..simulator import QATurn, UserSimulator


@dataclass
class ArmResult:
    """Output of one arm running on one task."""

    arm_name: str
    task_id: str
    qa_turns: list[QATurn]
    design: str
    raw_events: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "arm_name": self.arm_name,
            "task_id": self.task_id,
            "qa_turns": [{"question": t.question, "answer": t.answer} for t in self.qa_turns],
            "design": self.design,
            "raw_events": self.raw_events,
            "error": self.error,
        }


class ArmAdapter(Protocol):
    """An arm adapter takes a task + a fresh simulator, returns an ArmResult."""

    name: str

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult: ...
