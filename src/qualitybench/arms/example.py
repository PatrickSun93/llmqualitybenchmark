"""ExampleArm — file-based scoring of pre-generated ShipFlow output.

Instead of spawning ShipFlow live every run (slow, eats subscription quota,
non-deterministic), the user runs ShipFlow once per (task, branch) by hand,
copies the resulting `docs/shipflow/` tree into `examples/<task_id>/<arm>/`,
and the harness reads files from there.

Layout:

    examples/
    └── 01_habit_tracker/
        ├── main/
        │   └── docs/shipflow/
        │       ├── discovery/<slug>/
        │       │   ├── seed.md
        │       │   ├── questions.md
        │       │   ├── answers.md
        │       │   └── dialogue-*.md
        │       └── briefs/BRIEF-001-<slug>.md
        └── mono/
            └── docs/shipflow/...

Trade-offs vs live `ShipFlowArm`:
  +  Reproducible — same example dir → same scoring forever.
  +  Cheap — re-scoring after rubric tweaks costs nothing for the arm itself.
  +  Realistic — the answers reflect what a real user actually typed when
     running ShipFlow, not what the User Simulator approximates.
  -  Manual — user has to run ShipFlow once and copy output in.
  -  Loses transcript-level events (no spawn / phase / tool-call data).
  -  Canon drift risk: if the user's hand-typed answers don't match the
     task YAML's canon, scores get noisy. `verify_canon_consistency`
     catches this with a single LLM check.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import query_text
from ..schema import Task
from ..simulator import QATurn, UserSimulator
from .base import ArmResult


@dataclass
class ExampleArm:
    """Score a pre-generated ShipFlow output directory.

    Parameters
    ----------
    name:
        Arm name shown in the report ("main" or "mono").
    example_dir:
        Path to the ShipFlow output dir for this (task, arm).
        Typically ``examples/<task_id>/<arm>/``.
    verify_canon:
        If True (default), run a single Haiku check confirming that the
        hand-typed answers in ``answers.md`` are consistent with the task's
        canon. Surfaces drift before it skews scores.
    """

    name: str
    example_dir: Path
    verify_canon: bool = True

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult:
        # Simulator is intentionally unused — answers are baked into the dir.
        del simulator

        events: list[dict] = []
        if not self.example_dir.is_dir():
            return ArmResult(
                arm_name=self.name,
                task_id=task.id,
                qa_turns=[],
                design="",
                error=f"example dir not found: {self.example_dir}",
            )

        design = _read_brief(self.example_dir)
        if not design:
            return ArmResult(
                arm_name=self.name,
                task_id=task.id,
                qa_turns=[],
                design="",
                error=f"no BRIEF-*.md found under {self.example_dir}",
            )
        events.append({"type": "loaded_brief", "chars": len(design)})

        questions = _read_questions(self.example_dir)
        answers_text = _read_answers(self.example_dir)
        qa_turns = _pair_qa(questions, answers_text)
        events.append(
            {
                "type": "loaded_qa",
                "questions": len(questions),
                "answers_chars": len(answers_text),
                "paired_turns": len(qa_turns),
            }
        )

        if self.verify_canon and answers_text:
            warnings = verify_canon_consistency(task, answers_text)
            if warnings:
                events.append({"type": "canon_drift_warning", "issues": warnings})

        return ArmResult(
            arm_name=self.name,
            task_id=task.id,
            qa_turns=qa_turns,
            design=design,
            raw_events=events,
        )


# -----------------------------------------------------------------------------
# File parsing helpers
# -----------------------------------------------------------------------------


def _read_brief(example_dir: Path) -> str:
    """Locate the latest BRIEF-*.md anywhere under example_dir."""
    candidates = sorted(example_dir.rglob("BRIEF-*.md"))
    if not candidates:
        return ""
    return candidates[-1].read_text()


def _read_questions(example_dir: Path) -> list[str]:
    """Pull the questions.md content. Same parser as the live arm."""
    discovery_root = example_dir / "docs" / "shipflow" / "discovery"
    if not discovery_root.exists():
        return []
    candidates = sorted(discovery_root.glob("*/questions.md"))
    if not candidates:
        return []
    return _parse_questions(candidates[-1].read_text())


def _read_answers(example_dir: Path) -> str:
    discovery_root = example_dir / "docs" / "shipflow" / "discovery"
    if not discovery_root.exists():
        return ""
    candidates = sorted(discovery_root.glob("*/answers.md"))
    if not candidates:
        return ""
    return candidates[-1].read_text().strip()


def _parse_questions(text: str) -> list[str]:
    """Extract question strings from ShipFlow's questions.md.

    Accept bullets, numbered items, or any line ending with `?`.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        candidate = m.group(1).strip() if m else line
        if candidate.endswith("?"):
            out.append(candidate)
    return out


def _pair_qa(questions: list[str], answers_text: str) -> list[QATurn]:
    """Best-effort pair questions with chunks of answers.md.

    Strategy: split answers by blank lines. If chunk count matches question
    count, pair 1:1. Otherwise attach the full answer text to each question
    (downstream checks mostly need the questions; the bulk answer is fine).
    """
    if not questions:
        return []
    chunks = [c.strip() for c in re.split(r"\n\s*\n", answers_text) if c.strip()]
    if len(chunks) == len(questions):
        return [QATurn(q, a) for q, a in zip(questions, chunks, strict=True)]
    # Fallback: each question paired with the full answers blob.
    return [QATurn(q, answers_text) for q in questions]


# -----------------------------------------------------------------------------
# Canon-drift verification
# -----------------------------------------------------------------------------

VERIFY_SYSTEM = """You are checking whether a user's free-form answers to a discovery dialog \
are consistent with the constraints they've stated in their `canon`. The canon \
is the ground truth of what the user wants; the answers should not contradict it.

Output STRICT JSON:
{
  "issues": [
    {"canon_field": "<which canon entry was violated>", "answer_excerpt": "...", "rationale": "..."}
  ]
}
Empty array if no contradictions. No prose outside the JSON.
"""

VERIFY_PROMPT = """\
<canon>
{canon}
</canon>

<answers>
{answers}
</answers>

List places where the answers contradict or drift from the canon. Be strict but \
not nitpicky — flag only meaningful inconsistencies (a positional choice that \
the canon explicitly opposes, a constraint the answers ignore, etc.). \
Trivial wording differences are fine.
"""


def verify_canon_consistency(task: Task, answers_text: str) -> list[dict]:
    """Single-shot LLM check. Returns list of issue dicts (empty if clean)."""
    canon_block = task.canon.as_prompt_block()
    text = query_text(
        VERIFY_PROMPT.format(canon=canon_block, answers=answers_text),
        system=VERIFY_SYSTEM,
    )
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    payload = fenced.group(1).strip() if fenced else text.strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    issues = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(issues, list):
        return []
    return [i for i in issues if isinstance(i, dict)]
