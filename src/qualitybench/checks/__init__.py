"""Deterministic-ish check suite.

Runs all SPEC §5.1 procedural axes plus the deterministic part of Question
Quality (§5.2). Each check returns a `CheckResult`. The `run_pilot_checks`
helper runs only the 4 pilot dimensions; `run_all_checks` runs everything
deterministic.

All checks route LLM calls through `claude -p` (subscription) — no API key
required at this layer.
"""
from __future__ import annotations

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


def run_pilot_checks(task: Task, result: ArmResult) -> list[CheckResult]:
    """SPEC §12: 4 core pilot dimensions."""
    return [
        canon_consistency(task, result),
        critical_decision_coverage(task, result),
        question_coverage(task, result),
        decision_density(task, result),
    ]


def run_all_checks(task: Task, result: ArmResult) -> list[CheckResult]:
    """All deterministic checks (5 of the 9 dimensions). Judge-based ones live in judge.py."""
    return [
        canon_consistency(task, result),
        critical_decision_coverage(task, result),
        decision_density(task, result),
        scope_discipline(task, result),
        question_coverage(task, result),
    ]
