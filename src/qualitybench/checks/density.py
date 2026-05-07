"""Decision density: committed-decisions / total-decisions in the design.

Uses the shared extract_decisions helper. Score is the fraction of decisions
classified as `committed` (vs `punt` or `fuzzy`). Documents that handwave a lot
get a low score even if they look long.
"""
from __future__ import annotations

from anthropic import Anthropic

from ..arms.base import ArmResult
from ..schema import Task
from .base import CheckResult, ItemVerdict
from .extractor import extract_decisions


def decision_density(task: Task, result: ArmResult, client: Anthropic) -> CheckResult:
    decisions = extract_decisions(result.design, client=client)
    if not decisions:
        return CheckResult(name="decision_density", score=0.0, notes="no decisions extracted")

    committed = sum(1 for d in decisions if d.kind == "committed")
    items = [
        ItemVerdict(
            item=d.text[:150],
            verdict="yes" if d.kind == "committed" else "no",
            rationale=f"kind={d.kind}: {d.rationale}",
        )
        for d in decisions
    ]
    score = committed / len(decisions)
    return CheckResult(
        name="decision_density",
        score=score,
        items=items,
        notes=f"{committed}/{len(decisions)} committed",
    )
