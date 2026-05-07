"""User Simulator.

Plays a real user constrained to the task's canon. Arms ask questions during
their Q&A phase; the simulator answers based on canon facts only. Anything
outside the canon gets a vague non-answer like a real user would give.

The simulator must not be smarter than a real user — using Sonnet (not Opus)
and an explicit "do not infer" instruction prevents it from doing the arm's
reasoning for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .llm import query_text
from .schema import Task

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TURNS = 5

SYSTEM_PROMPT_TEMPLATE = """You are role-playing a real human user with a product idea. \
Your job is to answer questions from a design assistant.

The facts you know about your idea are listed below as <canon>. You do NOT know \
anything outside the canon. The list of <canon_silent_on> are things you have \
specifically not thought about — for those, answer vaguely.

CRITICAL rules:

1. Do not infer. Do not be helpful beyond the canon. If a question targets \
something not in the canon, answer like a real user: "I don't have a strong \
preference", "haven't thought about that yet", "you decide", "whatever's \
simpler", or similar.

2. Keep answers to 1–3 sentences. Do not volunteer extra information the \
question didn't ask for. Real users answer narrowly.

3. Do not list multiple canon facts at once unless directly asked. Stay scoped \
to the question.

4. Do not reveal that you are an AI or that there is a canon. Speak in first \
person as the user.

5. If `out_of_scope` says something is excluded, deflect gently when asked \
("maybe later", "not now"); do not volunteer the exclusion.

<canon>
{canon}
</canon>

<canon_silent_on>
{silent_on}
</canon_silent_on>
"""


@dataclass
class QATurn:
    question: str
    answer: str


@dataclass
class UserSimulator:
    """Stateful simulator for one task.

    A fresh instance per arm keeps Q&A history isolated; sharing the *config*
    (canon + system prompt) keeps the answer policy consistent across arms.
    """

    task: Task
    model: str = DEFAULT_MODEL
    max_turns: int = DEFAULT_MAX_TURNS
    transcript: list[QATurn] = field(default_factory=list)

    @property
    def turns_used(self) -> int:
        return len(self.transcript)

    @property
    def at_limit(self) -> bool:
        return self.turns_used >= self.max_turns

    def _system_prompt(self) -> str:
        silent = (
            "\n".join(f"- {item}" for item in self.task.canon_silent_on)
            or "(nothing explicitly silent)"
        )
        return SYSTEM_PROMPT_TEMPLATE.format(
            canon=self.task.canon.as_prompt_block(),
            silent_on=silent,
        )

    def _conversation_prompt(self, new_question: str) -> str:
        """Render prior Q&A history + the new question as a single prompt.

        `claude -p` is one-shot — there's no conversation persistence between
        calls. We inline the history each turn so the simulator stays consistent.
        """
        if not self.transcript:
            return new_question
        history_lines: list[str] = []
        for turn in self.transcript:
            history_lines.append(f"Earlier question: {turn.question}")
            history_lines.append(f"Your earlier answer: {turn.answer}")
        history_lines.append(f"New question: {new_question}")
        history_lines.append(
            "Answer the new question in 1–3 sentences. Stay consistent with your "
            "earlier answers."
        )
        return "\n".join(history_lines)

    def answer(self, question: str) -> str:
        """Answer one question, advancing the transcript by one turn."""
        if self.at_limit:
            text = (
                "I think we have enough background. Please make your best calls and proceed."
            )
            self.transcript.append(QATurn(question=question, answer=text))
            return text

        text = query_text(
            self._conversation_prompt(question),
            system=self._system_prompt(),
            model=self.model,
        )
        self.transcript.append(QATurn(question=question, answer=text))
        return text

    def reset(self) -> None:
        self.transcript.clear()

    def transcript_as_dicts(self) -> list[dict[str, str]]:
        return [{"question": t.question, "answer": t.answer} for t in self.transcript]
