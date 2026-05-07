"""End-to-end runner: orchestrates simulator + arms + checks, persists per-run artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

from .arms.base import ArmAdapter, ArmResult
from .checks import CheckResult, run_all_checks, run_pilot_checks
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


def run_arm(task: Task, arm: ArmAdapter, client: Anthropic, max_turns: int = 5) -> ArmResult:
    """Run one arm on one task with its own fresh simulator state.

    A fresh simulator per arm is required for fairness — sharing transcript
    across arms would let later arms benefit from earlier arms' Q&A.
    """
    simulator = UserSimulator(task=task, client=client, max_turns=max_turns)
    return arm.run(task=task, simulator=simulator)


def run_task(
    task: Task,
    arms: list[ArmAdapter],
    client: Anthropic,
    out_dir: Path,
    run_index: int = 1,
    max_turns: int = 5,
    pilot: bool = False,
    skip_checks: bool = False,
) -> list[ArmRun]:
    """Run every arm on a task, score with deterministic checks, persist artifacts."""
    runs: list[ArmRun] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / task.id / f"run_{run_index:02d}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for arm in arms:
        arm_result = run_arm(task=task, arm=arm, client=client, max_turns=max_turns)
        checks: list[CheckResult] = []
        if not skip_checks and not arm_result.error and arm_result.design.strip():
            check_fn = run_pilot_checks if pilot else run_all_checks
            checks = check_fn(task, arm_result, client)
        run = ArmRun(arm_result=arm_result, checks=checks)
        runs.append(run)
        path = run_dir / f"{arm.name}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))

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
                "scores": {c.name: round(c.score, 3) for c in r.checks},
            }
            for r in runs
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return runs
