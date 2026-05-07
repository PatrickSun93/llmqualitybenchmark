"""Scope Discipline / Instruction-following.

For every decision in the design, ask whether it traces to one of:
  (a) the original idea
  (b) a canon entry
  (c) a must_be_addressed critical decision
  (d) a question the user explicitly answered in Q&A

Decisions that trace to none of these — only to "general best practices" or
"common product wisdom" — are unrequested. Score = 1 - (unrequested / total).

Predicted to be Main's weakest axis: 22 specialized agents tend to
over-engineer by adding "best practices" the user never asked for.
"""
from __future__ import annotations

from anthropic import Anthropic

from ..arms.base import ArmResult
from ..schema import Task
from .base import CheckResult, ItemVerdict
from .extractor import classify_items, extract_decisions


def _build_anchors(task: Task, result: ArmResult) -> str:
    canon_lines = task.canon.as_prompt_block()
    must = "\n".join(f"- {x}" for x in task.must_be_addressed) or "(none)"
    qa = (
        "\n".join(f"Q: {t.question}\nA: {t.answer}" for t in result.qa_turns)
        or "(no Q&A)"
    )
    return (
        f"<idea>\n{task.idea.strip()}\n</idea>\n\n"
        f"<canon>\n{canon_lines}\n</canon>\n\n"
        f"<must_be_addressed>\n{must}\n</must_be_addressed>\n\n"
        f"<qa>\n{qa}\n</qa>"
    )


def scope_discipline(task: Task, result: ArmResult, client: Anthropic) -> CheckResult:
    decisions = extract_decisions(result.design, client=client)
    if not decisions:
        return CheckResult(name="scope_discipline", score=0.0, notes="no decisions extracted")

    anchors = _build_anchors(task, result)
    statements = [
        (
            f"This decision traces to the idea, the canon, the must_be_addressed list, "
            f"or an explicit Q&A answer: \"{d.text}\""
        )
        for d in decisions
    ]
    verdicts = classify_items(
        anchors,
        statements,
        client=client,
        instruction=(
            "Decide whether each decision is anchored in the user's stated inputs "
            "(idea / canon / must_be_addressed / Q&A). 'yes' if anchored. 'no' if it "
            "only traces to general best practices, common product wisdom, or the "
            "model's own inference. 'unclear' if the connection is debatable. "
            "Be strict: 'no' is the correct answer when the design adds something "
            "the user never asked about, even if it sounds reasonable."
        ),
    )

    yes = sum(1 for v in verdicts if v.verdict == "yes")
    unclear = sum(1 for v in verdicts if v.verdict == "unclear")
    no_count = sum(1 for v in verdicts if v.verdict == "no")
    score = (yes + 0.5 * unclear) / len(verdicts) if verdicts else 0.0

    items = [
        ItemVerdict(
            item=d.text[:150],
            verdict=v.verdict,
            rationale=v.rationale,
        )
        for d, v in zip(decisions, verdicts, strict=False)
    ]
    return CheckResult(
        name="scope_discipline",
        score=score,
        items=items,
        notes=f"{yes} anchored / {unclear} unclear / {no_count} unrequested out of {len(verdicts)}",
    )
