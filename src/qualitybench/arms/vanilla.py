"""Vanilla arm: bare Claude Code with only an `ask_user` MCP tool.

Per SPEC §4 and §13, this represents "what users get when they don't install any
plugin". We give the model exactly one extra capability — the `ask_user` MCP
tool that routes through to the User Simulator. No system prompt nudges
toward asking; if the model dives straight into a design, the Question Quality
dimension reflects that.

Routes through claude-agent-sdk (which spawns the `claude` CLI) so this arm
uses the user's subscription auth, consistent with the ShipFlow arms.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from ..schema import Task
from ..simulator import UserSimulator
from .base import ArmResult

DEFAULT_MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = (
    "The user has an open-ended product idea below. Produce a design document for it. "
    "You may use the `mcp__qualitybench__ask_user` tool to ask clarifying questions if helpful. "
    "Deliverable is the design only — do not write code."
)


def _make_ask_user_server(simulator: UserSimulator):
    """Build a fresh in-process MCP server bound to one simulator instance."""

    @tool(
        "ask_user",
        "Ask the user a single clarifying question about their idea. "
        "Use this when you need to know something the original idea did not cover.",
        {"question": str},
    )
    async def ask_user(args):
        question = str(args.get("question", "")).strip()
        if not question:
            return {
                "content": [
                    {"type": "text", "text": "(no question provided; cannot answer)"}
                ]
            }
        # The simulator is sync (it shells out to `claude -p`). From this async
        # callback we offload to a worker thread so we don't block the event loop.
        answer = await asyncio.to_thread(simulator.answer, question)
        return {"content": [{"type": "text", "text": answer}]}

    return create_sdk_mcp_server(name="qualitybench", version="0.1.0", tools=[ask_user])


@dataclass
class VanillaArm:
    name: str = "vanilla"
    model: str = DEFAULT_MODEL

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult:
        return asyncio.run(self._run_async(task, simulator))

    async def _run_async(self, task: Task, simulator: UserSimulator) -> ArmResult:
        events: list[dict] = []
        design_text = ""
        error: str | None = None

        mcp_server = _make_ask_user_server(simulator)
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"qualitybench": mcp_server},
            allowed_tools=["mcp__qualitybench__ask_user"],
            permission_mode="bypassPermissions",
            max_turns=20,
        )

        try:
            async for msg in query(prompt=task.idea, options=options):
                if isinstance(msg, AssistantMessage):
                    text = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
                    if text.strip():
                        # The latest plain-text reply is treated as the running
                        # candidate design; the final one wins.
                        design_text = text.strip()
                    events.append({"type": "assistant_text", "text": text[:2000]})
                elif isinstance(msg, ResultMessage):
                    events.append(
                        {
                            "type": "result",
                            "stop_reason": getattr(msg, "stop_reason", None),
                            "is_error": getattr(msg, "is_error", False),
                        }
                    )
                    break
                else:
                    events.append({"type": type(msg).__name__})
        except Exception as exc:  # noqa: BLE001 — surface SDK errors verbatim
            error = f"{type(exc).__name__}: {exc}"

        return ArmResult(
            arm_name=self.name,
            task_id=task.id,
            qa_turns=list(simulator.transcript),
            design=design_text,
            raw_events=events,
            error=error,
        )
