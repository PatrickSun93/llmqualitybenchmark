"""Deterministic-ish check suite.

Runs all SPEC §5.1 procedural axes plus the deterministic part of Question
Quality (§5.2). Each check returns a `CheckResult`. The `run_pilot_checks`
helper runs only the 4 pilot dimensions; `run_all_checks` runs everything
deterministic.
"""
from __future__ import annotations

from anthropic import Anthropic

from ..arms.base import ArmResult
from ..schema import Task
from .base import CheckResult
from .canon import canon_consistency
from .coverage import critical_decision_coverage, question_coverage
from .density import decision_density
from .scope import scope_discipline

__all__ = [
    "CheckResult",
    "canon_consistency",
    "critical_decision_coverage",
    "decision_density",
    "question_coverage",
    "run_all_checks",
    "run_pilot_checks",
    "scope_discipline",
]


def run_pilot_checks(task: Task, result: ArmResult, client: Anthropic) -> list[CheckResult]:
    """SPEC §12: 4 core pilot dimensions."""
    return [
        canon_consistency(task, result, client),
        critical_decision_coverage(task, result, client),
        question_coverage(task, result, client),
        decision_density(task, result, client),
    ]


def run_all_checks(task: Task, result: ArmResult, client: Anthropic) -> list[CheckResult]:
    """All deterministic checks (5 of the 9 dimensions). Judge-based ones live in judge.py."""
    return [
        canon_consistency(task, result, client),
        critical_decision_coverage(task, result, client),
        decision_density(task, result, client),
        scope_discipline(task, result, client),
        question_coverage(task, result, client),
    ]
