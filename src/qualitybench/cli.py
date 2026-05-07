"""Entry point for the qualitybench CLI."""
from __future__ import annotations

from pathlib import Path

import click
from anthropic import Anthropic
from rich.console import Console

from .arms.base import ArmAdapter
from .arms.shipflow import ShipFlowArm
from .arms.vanilla import VanillaArm
from .runner import run_task
from .schema import load_tasks

console = Console()


def _build_arms(
    names: list[str],
    client: Anthropic,
    shipflow_main_path: Path | None,
    shipflow_mono_path: Path | None,
) -> list[ArmAdapter]:
    arms: list[ArmAdapter] = []
    for name in names:
        if name == "vanilla":
            arms.append(VanillaArm(client=client))
        elif name == "main":
            if not shipflow_main_path:
                raise click.UsageError(
                    "--shipflow-main-path is required for arm 'main'"
                )
            arms.append(ShipFlowArm(name="main", plugin_path=shipflow_main_path))
        elif name == "mono":
            if not shipflow_mono_path:
                raise click.UsageError(
                    "--shipflow-mono-path is required for arm 'mono'"
                )
            arms.append(ShipFlowArm(name="mono", plugin_path=shipflow_mono_path))
        else:
            raise click.UsageError(f"unknown arm: {name}")
    return arms


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
@click.option("--max-turns", default=5, show_default=True, help="Q&A turn cap per arm.")
@click.option(
    "--shipflow-main-path",
    "shipflow_main_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    envvar="SHIPFLOW_MAIN_PATH",
    help="Path to ShipFlow main-branch checkout (contains .claude-plugin/).",
)
@click.option(
    "--shipflow-mono-path",
    "shipflow_mono_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    envvar="SHIPFLOW_MONO_PATH",
    help="Path to ShipFlow experiment/mono-agent checkout.",
)
def run(
    task_path: Path | None,
    tasks_dir: Path | None,
    runs: int,
    pilot: bool,
    arms: str,
    out_dir: Path,
    max_turns: int,
    shipflow_main_path: Path | None,
    shipflow_mono_path: Path | None,
) -> None:
    """Run the benchmark."""
    if not task_path and not tasks_dir:
        raise click.UsageError("Provide either --task or --tasks.")

    arm_names = [a.strip() for a in arms.split(",") if a.strip()]
    if pilot:
        runs = 1

    source = task_path or tasks_dir
    assert source is not None
    tasks = load_tasks(source)
    console.print(
        f"[bold]qualitybench[/bold] tasks={len(tasks)} arms={arm_names} "
        f"runs={runs} pilot={pilot}"
    )

    client = Anthropic()
    adapters = _build_arms(
        arm_names,
        client,
        shipflow_main_path=shipflow_main_path,
        shipflow_mono_path=shipflow_mono_path,
    )
    if not adapters:
        console.print("[red]no runnable arms; exiting[/red]")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        for run_idx in range(1, runs + 1):
            console.print(
                f"[cyan]→[/cyan] task={task.id} run={run_idx}/{runs} "
                f"arms={[a.name for a in adapters]}"
            )
            runs = run_task(
                task=task,
                arms=adapters,
                client=client,
                out_dir=out_dir,
                run_index=run_idx,
                max_turns=max_turns,
                pilot=pilot,
            )
            for r in runs:
                tag = "[red]ERR[/red]" if r.arm_result.error else "[green]OK[/green]"
                scores = " ".join(
                    f"{c.name}={c.score:.2f}" for c in r.checks
                ) or "(no checks)"
                console.print(
                    f"  {tag} {r.arm_result.arm_name}: "
                    f"{len(r.arm_result.qa_turns)} Q&A, "
                    f"{len(r.arm_result.design)} design chars | {scores}"
                )


if __name__ == "__main__":
    main()
