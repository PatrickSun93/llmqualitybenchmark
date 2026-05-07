"""End-to-end runner: orchestrates simulator + arms, persists per-run artifacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

from .arms.base import ArmAdapter, ArmResult
from .schema import Task
from .simulator import UserSimulator


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
) -> list[ArmResult]:
    """Run every arm on a task once, persist each ArmResult as JSON."""
    results: list[ArmResult] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / task.id / f"run_{run_index:02d}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for arm in arms:
        result = run_arm(task=task, arm=arm, client=client, max_turns=max_turns)
        results.append(result)
        path = run_dir / f"{arm.name}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    # Emit a small summary alongside the per-arm artifacts.
    summary = {
        "task_id": task.id,
        "idea": task.idea,
        "run_index": run_index,
        "timestamp": timestamp,
        "arms": [
            {
                "name": r.arm_name,
                "qa_turns": len(r.qa_turns),
                "design_chars": len(r.design),
                "error": r.error,
            }
            for r in results
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return results
