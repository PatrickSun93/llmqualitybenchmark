"""Entry point for the qualitybench CLI."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group()
def main() -> None:
    """Quality benchmark for Claude Code multi-agent plugins."""


@main.command()
@click.option(
    "--task",
    "task_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Single task YAML.",
)
@click.option(
    "--tasks",
    "tasks_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of task YAMLs.",
)
@click.option("--runs", default=1, show_default=True, help="Reruns per (task, arm).")
@click.option("--pilot", is_flag=True, help="Pilot mode: 1 run, 4 core dimensions only.")
@click.option(
    "--arms",
    default="vanilla,main,mono",
    show_default=True,
    help="Comma-separated arm names to run.",
)
@click.option(
    "--out",
    "out_dir",
    default="results",
    type=click.Path(path_type=Path),
    show_default=True,
)
def run(
    task_path: Path | None,
    tasks_dir: Path | None,
    runs: int,
    pilot: bool,
    arms: str,
    out_dir: Path,
) -> None:
    """Run the benchmark."""
    if not task_path and not tasks_dir:
        raise click.UsageError("Provide either --task or --tasks.")

    arm_names = [a.strip() for a in arms.split(",") if a.strip()]
    console.print(f"[bold]qualitybench[/bold] arms={arm_names} runs={runs} pilot={pilot}")
    console.print("[yellow]runner not yet wired — coming in commit 4[/yellow]")


if __name__ == "__main__":
    main()
