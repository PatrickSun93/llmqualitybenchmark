"""Shared LLM-based classifiers used by multiple checks.

Two primitives:
  - `classify_items`: given a design and a list of items, classify each as
    yes/no/unclear with a short rationale. Used by Canon consistency,
    Critical decision coverage, Question Quality coverage.
  - `extract_decisions`: scan a design and emit a structured list of every
    discrete decision, each tagged committed | punt | fuzzy. Used by
    Decision density and Scope Discipline.

Both go through `claude -p` (subscription auth, not API).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..llm import query_text
from .base import EXTRACTOR_MODEL, ItemVerdict


def _strip_json(text: str) -> str:
    """Pull a JSON array/object out of a possibly-fenced response."""
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


CLASSIFY_SYSTEM = """You evaluate whether each item in a list is honored / addressed by a design document.

For each item, output a verdict:
- "yes":     the item is addressed AND honored by the design
- "no":      the item is contradicted, ignored, or absent
- "unclear": the design touches the area but is too vague to call

Output STRICT JSON: an array of {"item": ..., "verdict": ..., "rationale": ...}.
Keep rationales under 25 words each. No prose outside the array."""


def classify_items(
    design: str,
    items: list[str],
    *,
    instruction: str,
    model: str = EXTRACTOR_MODEL,
) -> list[ItemVerdict]:
    """Yes/no classification per item."""
    if not items:
        return []
    prompt = (
        f"{instruction}\n\n"
        f"<design>\n{design}\n</design>\n\n"
        f"<items>\n"
        + "\n".join(f"{i + 1}. {it}" for i, it in enumerate(items))
        + "\n</items>\n\n"
        "Return JSON only."
    )
    text = query_text(prompt, system=CLASSIFY_SYSTEM, model=model)
    try:
        data = json.loads(_strip_json(text))
    except json.JSONDecodeError:
        return [
            ItemVerdict(item=it, verdict="unclear", rationale="extractor returned non-JSON")
            for it in items
        ]
    if not isinstance(data, list):
        return [
            ItemVerdict(item=it, verdict="unclear", rationale="extractor returned non-array")
            for it in items
        ]
    out: list[ItemVerdict] = []
    by_item = {entry.get("item", ""): entry for entry in data if isinstance(entry, dict)}
    for it in items:
        entry = by_item.get(it) or next(
            (e for e in data if isinstance(e, dict) and it in str(e.get("item", ""))),
            None,
        )
        if not entry:
            out.append(ItemVerdict(item=it, verdict="unclear", rationale="not classified"))
            continue
        verdict = str(entry.get("verdict", "unclear")).lower()
        if verdict not in {"yes", "no", "unclear"}:
            verdict = "unclear"
        out.append(
            ItemVerdict(
                item=it, verdict=verdict, rationale=str(entry.get("rationale", ""))[:200]
            )
        )
    return out


@dataclass
class Decision:
    text: str
    kind: str  # "committed" | "punt" | "fuzzy"
    rationale: str = ""

    def as_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "rationale": self.rationale}


EXTRACT_SYSTEM = """You extract decisions from a design document.

A "decision" is any place the document picks a direction for the product. Classify each:
- "committed": a clear pick. "We will use Postgres", "Auth: Auth0", "Deploy: Vercel"
- "punt":      explicitly deferred. "TBD", "needs further research", "to be decided"
- "fuzzy":     hedged or multi-option. "Use X or maybe Y", "consider A, B, or C"

Output STRICT JSON: an array of {"text": ..., "kind": ..., "rationale": ...}.
Keep `text` under 30 words (paraphrase faithfully). Keep `rationale` under 20 words.
No prose outside the array."""


def extract_decisions(
    design: str,
    *,
    model: str = EXTRACTOR_MODEL,
    max_decisions: int = 80,
) -> list[Decision]:
    if not design.strip():
        return []
    prompt = (
        f"<design>\n{design}\n</design>\n\n"
        f"List up to {max_decisions} decisions in document order. JSON only."
    )
    text = query_text(prompt, system=EXTRACT_SYSTEM, model=model)
    try:
        data = json.loads(_strip_json(text))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[Decision] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).lower()
        if kind not in {"committed", "punt", "fuzzy"}:
            continue
        out.append(
            Decision(
                text=str(entry.get("text", "")).strip(),
                kind=kind,
                rationale=str(entry.get("rationale", ""))[:200],
            )
        )
    return out[:max_decisions]
