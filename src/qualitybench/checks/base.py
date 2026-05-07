"""Common types for deterministic-ish checks.

Per SPEC §8.3, these checks should be deterministic where possible. In practice
we use Haiku as a small structured classifier — same prompt + temperature 0
gives near-identical outputs across reruns, while still handling natural
language better than brittle keyword matching. We surface the classifier
rationales so anyone can audit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

EXTRACTOR_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class ItemVerdict:
    """One item's classification result."""

    item: str
    verdict: str  # "yes" | "no" | "unclear"
    rationale: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    """Output of one check on one ArmResult."""

    name: str
    score: float  # 0.0..1.0; higher is better
    items: list[ItemVerdict] = field(default_factory=list)
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "items": [i.as_dict() for i in self.items],
            "notes": self.notes,
        }
