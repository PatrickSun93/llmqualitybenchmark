"""Vanilla-with-canon arm: bare Claude, but with the canon injected upfront.

This is the *fairness baseline* for the comparison. By giving plain Claude the
same canon information that ShipFlow's Q&A would have elicited, we isolate two
distinct kinds of lift:

  - (vanilla → vanilla-with-canon):     value of Q&A *as a capability* —
                                         arm-agnostic, plugin-agnostic.
  - (vanilla-with-canon → ShipFlow):    value of multi-agent reasoning beyond
                                         Q&A — i.e. the actual benchmark target.

This arm does NOT call the User Simulator. It already has all the answers,
so asking would be cheating (and contaminate Question Quality coverage). The
returned ArmResult has empty `qa_turns`, which causes Q&A-mediated dimensions
to mark themselves N/A (see judge.question_quality).

Per SPEC §4 fairness clause: this arm exists ONLY to neutralize the
structural bias in Canon-aware dimensions. It is not a candidate "best arm"
in the rankings — it's the upper bound for what plain Claude can do given
perfect context.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..llm import query_text
from ..schema import Task
from ..simulator import UserSimulator
from .base import ArmResult

DEFAULT_MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = (
    "You are designing software. The user has shared their idea below, plus "
    "the constraints and preferences they've already communicated. Use the "
    "context to produce a design document. "
    "Deliverable is the design only — do not write code."
)


def _build_prompt(task: Task) -> str:
    canon_block = task.canon.as_prompt_block()
    return (
        f"<idea>\n{task.idea.strip()}\n</idea>\n\n"
        f"<context_already_known>\n{canon_block}\n</context_already_known>\n\n"
        "Produce the design document now."
    )


@dataclass
class VanillaWithCanonArm:
    name: str = "vanilla-with-canon"
    model: str = DEFAULT_MODEL

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult:
        # `simulator` is intentionally unused — this arm has the canon already.
        del simulator
        try:
            design = query_text(
                _build_prompt(task),
                system=SYSTEM_PROMPT,
                model=self.model,
            )
            return ArmResult(
                arm_name=self.name,
                task_id=task.id,
                qa_turns=[],
                design=design,
                raw_events=[{"type": "single_shot_with_canon"}],
            )
        except Exception as exc:  # noqa: BLE001
            return ArmResult(
                arm_name=self.name,
                task_id=task.id,
                qa_turns=[],
                design="",
                error=f"{type(exc).__name__}: {exc}",
            )
