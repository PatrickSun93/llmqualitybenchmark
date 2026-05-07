"""Vanilla arm: bare Claude with only an ask_user tool — no plugin, no phase structure.

Per SPEC §4 and §13, this represents "what users get when they don't install any
plugin". The system prompt is minimal: only the compensation allowed by spec
("design only, no code"). We do NOT prompt the model to ask questions — if it
chooses to dive straight into a design without asking, that's the real Vanilla
behavior and the Question Quality dimension will reflect it.
"""
from __future__ import annotations

from anthropic import Anthropic

from ..schema import Task
from ..simulator import UserSimulator
from .base import ArmResult

DEFAULT_MODEL = "claude-opus-4-7"
MAX_ITERATIONS = 16  # safety cap on the tool-use loop

ASK_USER_TOOL = {
    "name": "ask_user",
    "description": (
        "Ask the user one clarifying question about their idea. "
        "Use this when you need to know something the original idea did not cover."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "A single, focused question for the user.",
            },
        },
        "required": ["question"],
    },
}

SYSTEM_PROMPT = (
    "The user has an open-ended product idea below. Produce a design document for it. "
    "You may use the `ask_user` tool to ask clarifying questions if helpful. "
    "Deliverable is the design only — do not write code."
)


class VanillaArm:
    name = "vanilla"

    def __init__(self, client: Anthropic, model: str = DEFAULT_MODEL):
        self.client = client
        self.model = model

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult:
        events: list[dict] = []
        messages: list[dict] = [{"role": "user", "content": task.idea}]

        design_text = ""
        error: str | None = None

        for iteration in range(MAX_ITERATIONS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[ASK_USER_TOOL],
                messages=messages,
            )
            events.append(
                {
                    "iteration": iteration,
                    "stop_reason": response.stop_reason,
                    "content_types": [b.type for b in response.content],
                }
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # Final response — capture as the design.
                design_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                break

            # The arm asked one or more questions this turn — route each to the simulator.
            tool_results: list[dict] = []
            for tu in tool_uses:
                if tu.name != "ask_user":
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": "Unknown tool; please use ask_user only.",
                            "is_error": True,
                        }
                    )
                    continue
                question = tu.input.get("question", "")
                answer = simulator.answer(question)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": answer}
                )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            error = f"hit MAX_ITERATIONS={MAX_ITERATIONS} without producing a design"

        return ArmResult(
            arm_name=self.name,
            task_id=task.id,
            qa_turns=list(simulator.transcript),
            design=design_text,
            raw_events=events,
            error=error,
        )
