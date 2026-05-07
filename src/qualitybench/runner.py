"""End-to-end runner: orchestrates simulator + arms + checks, persists artifacts.

All LLM calls (simulator, checks, judges, arms) route through `claude -p` or
claude-agent-sdk; nothing here uses the Anthropic API directly. The user's
Claude Code subscription auth handles billing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .arms.base import ArmAdapter, ArmResult
from .checks import CheckResult, run_all_deterministic_checks, run_pilot_checks
from .judge import (
    DIMENSION_DEFINITIONS,
    internal_consistency,
    pairwise_tournament,
    question_quality,
)
from .schema import Task
from .simulator import UserSimulator


@dataclass
class ArmRun:
    """Per-(task, arm, run) bundle: arm output plus check scores."""

    arm_result: ArmResult
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "arm_result": self.arm_result.to_dict(),
            "checks": [c.as_dict() for c in self.checks],
        }


PAIRWISE_DIMENSIONS = list(DIMENSION_DEFINITIONS.keys())


def run_arm(task: Task, arm: ArmAdapter, max_turns: int = 5) -> ArmResult:
    """Run one arm on one task with its own fresh simulator state.

    A fresh simulator per arm is required for fairness — sharing transcript
    across arms would let later arms benefit from earlier arms' Q&A.
    """
    simulator = UserSimulator(task=task, max_turns=max_turns)
    return arm.run(task=task, simulator=simulator)


def run_task(
    task: Task,
    arms: list[ArmAdapter],
    out_dir: Path,
    run_index: int = 1,
    max_turns: int = 5,
    pilot: bool = False,
    skip_checks: bool = False,
) -> list[ArmRun]:
    """Run every arm on a task, score with checks, run pairwise tournament, persist."""
    runs: list[ArmRun] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / task.id / f"run_{run_index:02d}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for arm in arms:
        arm_result = run_arm(task=task, arm=arm, max_turns=max_turns)
        checks: list[CheckResult] = []
        if not skip_checks and not arm_result.error and arm_result.design.strip():
            check_fn = run_pilot_checks if pilot else run_all_deterministic_checks
            checks = list(check_fn(task, arm_result))
            if not pilot:
                checks.append(internal_consistency(task, arm_result))
                checks.append(question_quality(task, arm_result, max_turns=max_turns))
        run = ArmRun(arm_result=arm_result, checks=checks)
        runs.append(run)
        path = run_dir / f"{arm.name}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))

    pairwise: dict[str, dict[str, int]] = {}
    if not pilot:
        for dim in PAIRWISE_DIMENSIONS:
            # Only rank arms whose individual check on this dim is not N/A.
            # E.g. question_quality is only ranked among arms that did Q&A.
            eligible: dict[str, ArmResult] = {}
            for r in runs:
                if r.arm_result.error or not r.arm_result.design.strip():
                    continue
                score = next((c.score for c in r.checks if c.name == dim), None)
                if score is None:
                    continue
                eligible[r.arm_result.arm_name] = r.arm_result
            if len(eligible) >= 2:
                pairwise[dim] = pairwise_tournament(
                    dimension=dim, task=task, arm_results=eligible
                )

    summary = {
        "task_id": task.id,
        "idea": task.idea,
        "run_index": run_index,
        "timestamp": timestamp,
        "pilot": pilot,
        "arms": [
            {
                "name": r.arm_result.arm_name,
                "qa_turns": len(r.arm_result.qa_turns),
                "design_chars": len(r.arm_result.design),
                "error": r.arm_result.error,
                "scores": {
                    c.name: (None if c.score is None else round(c.score, 3))
                    for c in r.checks
                },
            }
            for r in runs
        ],
        "pairwise_ranks": pairwise,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return runs
