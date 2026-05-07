"""Judge-based checks (Opus 4.7 by default).

These are the dimensions that don't reduce cleanly to extractor patterns:
  - internal_consistency:   find contradiction pairs in the design
  - question_precision:     classify each arm-asked question vague vs sharp
  - question_quality:       composite of coverage (commit 6) + precision +
                            restraint (deterministic ratio) + non_redundancy
  - pairwise_tournament:    per-dimension 3-arm ranking by a judge

The anti-bias clause from SPEC Appendix B is prepended to every judge prompt
to suppress format / length / formality bias.

All judge calls route through `claude -p` (subscription).
"""
from __future__ import annotations

import json
import re

from .arms.base import ArmResult
from .checks.base import CheckResult, ItemVerdict
from .checks.coverage import question_coverage
from .llm import query_text
from .schema import Task

JUDGE_MODEL = "claude-opus-4-7"

ANTI_BIAS = """\
Critical evaluation guidelines (apply to ALL judgments below):

1. Do not reward output for being more structured, longer, or having more \
headers. Reward only substantive content. A 200-word focused decision \
document beats a 2000-word document with the same decisions buried in \
scaffolding.

2. Do not reward formality of tone. A casual but precise design beats a \
formal but vague one.

3. Do not penalize an output for stating "I don't know" or "this needs \
further discussion" if those are honest assessments. Penalize ONLY when the \
document handwaves on a question it should have answered given the available \
canon.

4. When comparing outputs, focus on:
   - Did each address the same set of decisions?
   - Are decisions traceable to inputs (idea + Q&A)?
   - Are there internal contradictions?
   - Are constraints from the canon honored?
"""


def _strip_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


# -----------------------------------------------------------------------------
# Internal consistency
# -----------------------------------------------------------------------------

INTERNAL_CONSISTENCY_PROMPT = """\
{anti_bias}

You are checking a design document for INTERNAL CONTRADICTIONS only.

A contradiction is a pair of decisions/claims in the SAME document that cannot \
both be true. Examples: "We use Postgres" + "Data layer is DynamoDB"; "MVP \
ships in 2 weeks" + "Authentication via SSO with custom IDP".

You are NOT judging whether decisions are good — only whether they conflict \
with each other.

Output STRICT JSON:
{{
  "contradictions": [
    {{"pair": "A vs B", "rationale": "..."}}
  ]
}}
Empty array if none. No prose outside the JSON.

<design>
{design}
</design>
"""


def internal_consistency(task: Task, result: ArmResult) -> CheckResult:
    if not result.design.strip():
        return CheckResult(name="internal_consistency", score=0.0, notes="empty design")

    text = query_text(
        INTERNAL_CONSISTENCY_PROMPT.format(anti_bias=ANTI_BIAS, design=result.design),
        model=JUDGE_MODEL,
    )
    try:
        data = json.loads(_strip_json(text))
        contradictions = data.get("contradictions") or []
    except json.JSONDecodeError:
        contradictions = []

    items = [
        ItemVerdict(
            item=str(c.get("pair", ""))[:200],
            verdict="no",  # contradictions are bad
            rationale=str(c.get("rationale", ""))[:200],
        )
        for c in contradictions
        if isinstance(c, dict)
    ]
    n = min(len(items), 5)
    score = max(0.0, 1.0 - 0.2 * n)
    return CheckResult(
        name="internal_consistency",
        score=score,
        items=items,
        notes=f"{len(items)} contradiction pair(s) found",
    )


# -----------------------------------------------------------------------------
# Question Quality (composite)
# -----------------------------------------------------------------------------

QUESTION_PRECISION_PROMPT = """\
{anti_bias}

For each question below, classify how SHARP it is:
- "sharp":   targets a specific decision with a clear answer space \
("B2B or B2C?", "subscription or one-time?", "auth via SSO or password?")
- "vague":   open-ended, exploratory, or platitude \
("what are your thoughts on X?", "tell me about your users")

Output STRICT JSON: an array of {{"question": ..., "verdict": "sharp"|"vague"}}.
No prose outside the array.

<questions>
{questions}
</questions>
"""


def _question_precision_verdicts(questions: list[str]) -> list[ItemVerdict]:
    if not questions:
        return []
    text = query_text(
        QUESTION_PRECISION_PROMPT.format(
            anti_bias=ANTI_BIAS,
            questions="\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)),
        ),
        model=JUDGE_MODEL,
    )
    try:
        data = json.loads(_strip_json(text))
    except json.JSONDecodeError:
        return [ItemVerdict(item=q, verdict="unclear", rationale="parse failure") for q in questions]
    if not isinstance(data, list):
        return [ItemVerdict(item=q, verdict="unclear", rationale="non-array") for q in questions]
    out: list[ItemVerdict] = []
    by_q = {str(e.get("question", "")): e for e in data if isinstance(e, dict)}
    for q in questions:
        entry = by_q.get(q) or next(
            (e for e in data if isinstance(e, dict) and q in str(e.get("question", ""))),
            None,
        )
        verdict = str((entry or {}).get("verdict", "unclear")).lower()
        if verdict == "sharp":
            v = "yes"
        elif verdict == "vague":
            v = "no"
        else:
            v = "unclear"
        out.append(ItemVerdict(item=q, verdict=v))
    return out


def _restraint_score(result: ArmResult, max_turns: int) -> float:
    """Fewer questions relative to the cap → higher restraint."""
    n = len(result.qa_turns)
    if max_turns <= 0:
        return 1.0
    return max(0.0, 1.0 - n / max_turns)


def _non_redundancy_score(result: ArmResult) -> float:
    if len(result.qa_turns) < 2:
        return 1.0
    questions = "\n".join(f"{i + 1}. {t.question}" for i, t in enumerate(result.qa_turns))
    text = query_text(
        (
            f"{ANTI_BIAS}\n\nCount how many of the following questions are "
            "redundant — i.e., already answered by an earlier question or the "
            "user's idea. Output STRICT JSON: "
            '{"redundant_count": <int>, "total": <int>}.\n\n'
            f"<questions>\n{questions}\n</questions>"
        ),
        model=JUDGE_MODEL,
    )
    try:
        data = json.loads(_strip_json(text))
        red = int(data.get("redundant_count", 0))
        total = int(data.get("total", len(result.qa_turns)))
        if total <= 0:
            return 1.0
        return max(0.0, 1.0 - red / total)
    except (json.JSONDecodeError, ValueError, TypeError):
        return 1.0


def question_quality(task: Task, result: ArmResult, max_turns: int = 5) -> CheckResult:
    """Composite of coverage + precision + restraint + non-redundancy."""
    coverage = question_coverage(task, result)
    if not result.qa_turns:
        score = (coverage.score + 1.0 + 1.0 + 1.0) / 4
        return CheckResult(
            name="question_quality",
            score=score,
            notes="arm asked no questions",
        )

    questions = [t.question for t in result.qa_turns]
    precision_verdicts = _question_precision_verdicts(questions)
    sharp = sum(1 for v in precision_verdicts if v.verdict == "yes")
    precision_score = sharp / len(precision_verdicts) if precision_verdicts else 0.0

    restraint = _restraint_score(result, max_turns=max_turns)
    non_redundancy = _non_redundancy_score(result)

    score = (coverage.score + precision_score + restraint + non_redundancy) / 4
    notes = (
        f"coverage={coverage.score:.2f} precision={precision_score:.2f} "
        f"restraint={restraint:.2f} non_redundancy={non_redundancy:.2f}"
    )
    return CheckResult(
        name="question_quality",
        score=score,
        items=precision_verdicts,
        notes=notes,
    )


# -----------------------------------------------------------------------------
# Pairwise tournament
# -----------------------------------------------------------------------------

PAIRWISE_PROMPT = """\
{anti_bias}

You are ranking three design documents on a single dimension: **{dimension}**.

Definition of {dimension}: {definition}

Order the three labeled designs from BEST to WORST on this dimension only. \
Output STRICT JSON: {{"ranking": ["best_label", "middle_label", "worst_label"], \
"rationale": "..."}}.

<designs>
{block}
</designs>
"""

DIMENSION_DEFINITIONS = {
    "canon_consistency": "the design honors the user's stated constraints (canon).",
    "internal_consistency": "the design is free of contradictions.",
    "decision_density": (
        "the design commits to specific choices rather than punting or staying vague."
    ),
    "scope_discipline": (
        "the design avoids adding features the user did not ask for "
        "(no over-engineering)."
    ),
    "critical_decision_coverage": (
        "the design provides committed answers to every critical decision."
    ),
    "question_quality": (
        "the arm's clarifying questions covered the right ambiguities, were sharp, "
        "non-redundant, and not excessive in number."
    ),
}


def pairwise_tournament(
    dimension: str,
    task: Task,
    arm_results: dict[str, ArmResult],
) -> dict[str, int]:
    """Rank arms on `dimension`. Returns {arm_name: rank} where 1 is best."""
    if dimension not in DIMENSION_DEFINITIONS:
        raise ValueError(f"unknown dimension {dimension!r}")
    if len(arm_results) < 2:
        return {name: 1 for name in arm_results}

    labels = ["A", "B", "C", "D", "E"][: len(arm_results)]
    label_to_arm = dict(zip(labels, arm_results.keys(), strict=False))
    block = "\n\n".join(
        f"<design label=\"{label}\">\n{arm_results[label_to_arm[label]].design}\n</design>"
        for label in labels
    )

    text = query_text(
        PAIRWISE_PROMPT.format(
            anti_bias=ANTI_BIAS,
            dimension=dimension,
            definition=DIMENSION_DEFINITIONS[dimension],
            block=block,
        ),
        model=JUDGE_MODEL,
    )
    try:
        data = json.loads(_strip_json(text))
        ranking = data.get("ranking") or []
    except json.JSONDecodeError:
        ranking = []

    ranks: dict[str, int] = {}
    for pos, label in enumerate(ranking, start=1):
        arm = label_to_arm.get(str(label).strip())
        if arm and arm not in ranks:
            ranks[arm] = pos
    last = len(arm_results)
    for arm in arm_results:
        ranks.setdefault(arm, last)
    return ranks
