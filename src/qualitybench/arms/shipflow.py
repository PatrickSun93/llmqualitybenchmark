"""ShipFlow arm adapters (Main and Mono branches).

Both arms share the same skeleton: load the ShipFlow plugin into a Claude Agent
SDK session, run /sf-discover, read questions.md, route questions through the
shared User Simulator, send answers back, run /sf-brief, extract the brief as
the design output.

The only difference between Main and Mono arms is the plugin path — Main
points at the multi-agent main checkout, Mono at the experiment/mono-agent
checkout. Per SPEC §4: "唯一变量是 role 注入位置" (system prompt vs user
content). The harness itself does not need to know which is which.

Each (task, arm, run) gets a fresh tempdir as cwd so ShipFlow's file
operations are isolated and reproducible.
"""
from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from ..schema import Task
from ..simulator import UserSimulator
from .base import ArmResult

DEFAULT_MODEL = "claude-opus-4-7"
SDK_MAX_TURNS = 40

CLOSING_INSTRUCTION = (
    "After /sf-brief produces the brief, stop. Do not run /sf-build, /sf-verify, "
    "/sf-ship, or any later phase. The deliverable is the brief content only — "
    "this benchmark stops at the design phase."
)


@dataclass
class ShipFlowArm:
    """Adapter for one ShipFlow variant.

    Parameters
    ----------
    name:
        Logical arm name ("main" or "mono") used in the result table.
    plugin_path:
        Filesystem path to the ShipFlow plugin checkout (the directory containing
        ``.claude-plugin/marketplace.json``).
    """

    name: str
    plugin_path: Path
    model: str = DEFAULT_MODEL

    def run(self, task: Task, simulator: UserSimulator) -> ArmResult:
        return asyncio.run(self._run_async(task, simulator))

    async def _run_async(self, task: Task, simulator: UserSimulator) -> ArmResult:
        events: list[dict] = []
        design = ""
        error: str | None = None

        with tempfile.TemporaryDirectory(prefix=f"qb-{self.name}-") as workdir_str:
            workdir = Path(workdir_str)
            options = ClaudeAgentOptions(
                model=self.model,
                cwd=str(workdir),
                plugins=[{"type": "local", "path": str(self.plugin_path)}],
                permission_mode="bypassPermissions",
                max_turns=SDK_MAX_TURNS,
            )
            try:
                async with ClaudeSDKClient(options=options) as sdk:
                    # Turn 1: kick off discovery.
                    discover_prompt = (
                        f'/sf-discover "{_escape(task.idea.strip())}"\n\n'
                        f"{CLOSING_INSTRUCTION}"
                    )
                    await sdk.query(discover_prompt)
                    events.append({"turn": "discover", "events": await _drain(sdk)})

                    # Read the questions ShipFlow wrote to disk.
                    questions = _read_questions(workdir)
                    if not questions:
                        error = "no questions.md produced by /sf-discover"
                        return ArmResult(
                            arm_name=self.name,
                            task_id=task.id,
                            qa_turns=list(simulator.transcript),
                            design="",
                            raw_events=events,
                            error=error,
                        )

                    # Turn 2: route each question through the simulator and reply.
                    answer_lines: list[str] = []
                    for idx, q in enumerate(questions, start=1):
                        a = await asyncio.to_thread(simulator.answer, q)
                        answer_lines.append(f"Q{idx}: {q}\nA{idx}: {a}\n")
                    answer_blob = "\n".join(answer_lines)

                    await sdk.query(answer_blob)
                    events.append({"turn": "answers", "events": await _drain(sdk)})

                    # Turn 3: run /sf-brief and capture the resulting brief.
                    await sdk.query("/sf-brief\n\n" + CLOSING_INSTRUCTION)
                    events.append({"turn": "brief", "events": await _drain(sdk)})

                    design = _read_brief(workdir) or ""
                    if not design:
                        error = "no BRIEF-*.md produced by /sf-brief"

            except Exception as exc:  # noqa: BLE001 — surface SDK errors verbatim
                error = f"{type(exc).__name__}: {exc}"

        return ArmResult(
            arm_name=self.name,
            task_id=task.id,
            qa_turns=list(simulator.transcript),
            design=design,
            raw_events=events,
            error=error,
        )


async def _drain(sdk: ClaudeSDKClient) -> list[dict]:
    """Drain one response from the SDK client into a compact event log."""
    log: list[dict] = []
    async for msg in sdk.receive_response():
        if isinstance(msg, AssistantMessage):
            text = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
            log.append({"type": "assistant_text", "text": text[:2000]})
        elif isinstance(msg, ResultMessage):
            log.append(
                {
                    "type": "result",
                    "stop_reason": getattr(msg, "stop_reason", None),
                    "is_error": getattr(msg, "is_error", False),
                }
            )
            break
        else:
            log.append({"type": type(msg).__name__})
    return log


def _read_questions(workdir: Path) -> list[str]:
    """Locate questions.md under docs/shipflow/discovery/<slug>/ and parse it."""
    discovery_root = workdir / "docs" / "shipflow" / "discovery"
    if not discovery_root.exists():
        return []
    candidates = sorted(discovery_root.glob("*/questions.md"))
    if not candidates:
        return []
    text = candidates[-1].read_text()
    return _parse_questions(text)


def _parse_questions(text: str) -> list[str]:
    """Extract individual questions from ShipFlow's questions.md.

    ShipFlow writes questions as a deduped list. We accept lines that look like
    bullets, numbered items, or end with a question mark.
    """
    questions: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        candidate = m.group(1).strip() if m else line
        if candidate.endswith("?"):
            questions.append(candidate)
    return questions


def _read_brief(workdir: Path) -> str:
    """Locate the latest BRIEF-*.md ShipFlow produced and return its content."""
    candidates = sorted((workdir / "docs" / "shipflow").rglob("BRIEF-*.md"))
    if not candidates:
        return ""
    return candidates[-1].read_text()


def _escape(s: str) -> str:
    """Escape characters that would break the shell-style /sf-discover argument."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
