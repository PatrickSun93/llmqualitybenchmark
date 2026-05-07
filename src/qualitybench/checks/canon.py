"""Canon consistency check.

Each non-empty canon field becomes a yes/no/unclear question for the classifier:
"Is this canon constraint honored by the design?". Score = (yes count + 0.5 * unclear)
/ total fields. Negative constraints (key_dislike, out_of_scope) are phrased as
"avoided" — the classifier judges presence/absence accordingly.
"""
from __future__ import annotations

from ..arms.base import ArmResult
from ..schema import Task
from .base import CheckResult
from .extractor import classify_items


# Canon fields that express a NEGATIVE constraint ("user does not want X").
# Phrased as "avoided" so a positive verdict means the design respected the
# negative constraint.
NEGATIVE_FIELDS = {"key_dislike", "out_of_scope"}


def _build_items(task: Task) -> list[tuple[str, str]]:
    """Return [(field_name, statement_for_classifier), ...] for non-empty canon fields."""
    items: list[tuple[str, str]] = []
    canon_dump = task.canon.model_dump(exclude={"extra"}, exclude_none=True)
    canon_dump.update(task.canon.extra)
    for field, value in canon_dump.items():
        v = str(value).strip()
        if not v:
            continue
        if field in NEGATIVE_FIELDS:
            statement = (
                f"The design avoids what the user dislikes / excluded under "
                f"`{field}`: {v}"
            )
        else:
            statement = f"The design honors `{field}`: {v}"
        items.append((field, statement))
    return items


def canon_consistency(task: Task, result: ArmResult) -> CheckResult:
    pairs = _build_items(task)
    if not pairs or not result.design.strip():
        return CheckResult(name="canon_consistency", score=0.0, notes="no canon or empty design")

    statements = [s for _, s in pairs]
    verdicts = classify_items(
        result.design,
        statements,
        instruction=(
            "Each item below is a constraint or preference from the user's canon. "
            "Decide whether the design honors it. Be strict: 'yes' only if clearly "
            "honored; 'no' if contradicted or ignored; 'unclear' if the design is "
            "vague where the canon is specific."
        ),
    )

    yes = sum(1 for v in verdicts if v.verdict == "yes")
    unclear = sum(1 for v in verdicts if v.verdict == "unclear")
    score = (yes + 0.5 * unclear) / len(verdicts) if verdicts else 0.0
    return CheckResult(name="canon_consistency", score=score, items=verdicts)
