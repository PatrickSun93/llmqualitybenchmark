"""LLM helper that routes through `claude -p` (subscription) instead of the API.

Every harness LLM call goes through `query_text()`. Under the hood:
    claude -p --bare --model <model> --append-system-prompt <system>
            --output-format json
with the prompt fed via stdin. `--bare` skips hooks / plugin sync / CLAUDE.md
auto-discovery so each utility call is fast and lean.

Tradeoffs vs raw Anthropic API:
  - Auth is whatever `claude login` is set to — Max subscription, not API.
  - Each call spawns a fresh CLI process (~1-2s overhead per call).
  - Each call counts as one "message" in subscription quota, regardless of
    token count.
  - We lose structured tool-use (use claude-agent-sdk if you need tools —
    see arms/vanilla.py for the MCP pattern).

For tool-using flows (the Vanilla arm), bypass this helper and use
claude-agent-sdk's query() / ClaudeSDKClient directly with an MCP tool.
"""
from __future__ import annotations

import json
import subprocess

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TIMEOUT = 180


class ClaudeCodeError(RuntimeError):
    pass


def query_text(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """One-shot text query via `claude -p`. Returns the assistant text only."""
    cmd: list[str] = [
        "claude",
        "-p",
        "--bare",
        "--model",
        model,
        "--output-format",
        "json",
    ]
    if system:
        cmd.extend(["--append-system-prompt", system])

    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise ClaudeCodeError(
            f"claude -p exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )

    # `--output-format json` produces a single JSON object with `result` field.
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        # Fall back to raw stdout in case --output-format json wasn't honored.
        if proc.stdout.strip():
            return proc.stdout.strip()
        raise ClaudeCodeError(f"could not parse JSON output: {exc}") from exc

    if isinstance(data, dict):
        # The `result` field is the model's textual reply.
        text = data.get("result") or data.get("text") or ""
        return str(text).strip()
    return str(data).strip()
