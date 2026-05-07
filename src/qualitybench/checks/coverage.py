"""Critical decision coverage and Question Quality coverage.

Both follow the same shape — given a list of items the design or arm should hit,
ask the classifier per item. Score = hit ratio.
"""
from __future__ import annotations

from anthropic import Anthropic

from ..arms.base import ArmResult
from ..schema import Task
from .base import CheckResult
from .extractor import classify_items


def critical_decision_coverage(
    task: Task, result: ArmResult, client: Anthropic
) -> CheckResult:
    items = task.must_be_addressed
    if not items or not result.design.strip():
        return CheckResult(name="critical_decision_coverage", score=0.0, notes="empty inputs")

    statements = [
        f"The design provides a committed answer to: {item}"
        for item in items
    ]
    verdicts = classify_items(
        result.design,
        statements,
        client=client,
        instruction=(
            "Each item is a critical decision the design must make a committed "
            "choice about. Mark 'yes' only if the design picks a specific approach; "
            "'no' if the question is not addressed; 'unclear' if mentioned but vague."
        ),
    )
    # Map back to the original item phrasing for readability.
    for v, item in zip(verdicts, items, strict=False):
        v.item = item

    yes = sum(1 for v in verdicts if v.verdict == "yes")
    return CheckResult(
        name="critical_decision_coverage",
        score=yes / len(verdicts) if verdicts else 0.0,
        items=verdicts,
    )


def question_coverage(task: Task, result: ArmResult, client: Anthropic) -> CheckResult:
    """Of the task's key_ambiguities, how many did the arm raise as a question?"""
    items = task.key_ambiguities
    if not items:
        return CheckResult(name="question_coverage", score=0.0, notes="no key_ambiguities")
    if not result.qa_turns:
        # Arm asked nothing — coverage is 0 by definition.
        return CheckResult(
            name="question_coverage",
            score=0.0,
            items=[],
            notes="arm asked no questions",
        )

    asked = "\n".join(f"- {t.question}" for t in result.qa_turns)
    statements = [
        f"At least one question in <asked> targets the ambiguity: {item}"
        for item in items
    ]
    verdicts = classify_items(
        f"<asked>\n{asked}\n</asked>",
        statements,
        client=client,
        instruction=(
            "Each item is an ambiguity the arm should ideally have asked about. "
            "Mark 'yes' if any of the asked questions targets it; 'no' otherwise."
        ),
    )
    for v, item in zip(verdicts, items, strict=False):
        v.item = item

    yes = sum(1 for v in verdicts if v.verdict == "yes")
    return CheckResult(
        name="question_coverage",
        score=yes / len(verdicts) if verdicts else 0.0,
        items=verdicts,
    )
