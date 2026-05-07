"""Entry point for the qualitybench CLI.

All LLM calls go through `claude -p` (claude-agent-sdk) — i.e. the user's
Claude Code subscription. No ANTHROPIC_API_KEY required at the harness level
(though the user must be logged in to claude CLI: `claude login`).
"""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from .arms.base import ArmAdapter
from .arms.example import ExampleArm
from .arms.shipflow import ShipFlowArm
from .arms.vanilla import VanillaArm
from .arms.vanilla_with_canon import VanillaWithCanonArm
from .report import build_report
from .runner import run_task
from .schema import load_tasks

console = Console()


def _build_arms(
    names: list[str],
    *,
    task_id: str,
    shipflow_main_path: Path | None,
    shipflow_mono_path: Path | None,
    examples_dir: Path | None,
    verify_examples: bool,
) -> list[ArmAdapter]:
    """Build adapters for `names`, picking ExampleArm or ShipFlowArm per task.

    When --examples-dir is provided AND examples/<task_id>/<name>/ exists, the
    arm runs offline against pre-generated files. Otherwise it falls back to
    live ShipFlow invocation via claude-agent-sdk.
    """
    arms: list[ArmAdapter] = []
    for name in names:
        if name == "vanilla":
            arms.append(VanillaArm())
        elif name == "vanilla-with-canon":
            arms.append(VanillaWithCanonArm())
        elif name in ("main", "mono"):
            example_path = (
                examples_dir / task_id / name if examples_dir else None
            )
            if example_path and example_path.is_dir():
                arms.append(
                    ExampleArm(
                        name=name,
                        example_dir=example_path,
                        verify_canon=verify_examples,
                    )
                )
                continue
            # Fall back to live invocation.
            plugin_path = (
                shipflow_main_path if name == "main" else shipflow_mono_path
            )
            if not plugin_path:
                raise click.UsageError(
                    f"arm '{name}' needs either an entry under "
                    f"--examples-dir/{task_id}/{name}/ or "
                    f"--shipflow-{name}-path for live mode"
                )
            arms.append(ShipFlowArm(name=name, plugin_path=plugin_path))
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
    default="vanilla,vanilla-with-canon,main,mono",
    show_default=True,
    help=(
        "Comma-separated arm names. `vanilla-with-canon` is the fairness "
        "baseline (Vanilla + canon injected) — keep it in to neutralize bias "
        "against bare Claude on Q&A-mediated dimensions."
    ),
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
@click.option(
    "--examples-dir",
    "examples_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    envvar="QB_EXAMPLES_DIR",
    help=(
        "Directory of pre-generated ShipFlow output. When set, arms 'main' "
        "and 'mono' read from <dir>/<task_id>/<arm>/ instead of running "
        "ShipFlow live. Falls back to live mode if a (task, arm) entry is "
        "missing."
    ),
)
@click.option(
    "--verify-examples/--no-verify-examples",
    "verify_examples",
    default=True,
    show_default=True,
    help="Single-shot Haiku check that user-typed answers match task canon.",
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
    examples_dir: Path | None,
    verify_examples: bool,
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

    out_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        adapters = _build_arms(
            arm_names,
            task_id=task.id,
            shipflow_main_path=shipflow_main_path,
            shipflow_mono_path=shipflow_mono_path,
            examples_dir=examples_dir,
            verify_examples=verify_examples,
        )
        if not adapters:
            console.print("[red]no runnable arms; skipping task[/red]")
            continue

        for run_idx in range(1, runs + 1):
            modes = [
                f"{a.name}({type(a).__name__.replace('Arm','').lower()})"
                for a in adapters
            ]
            console.print(
                f"[cyan]→[/cyan] task={task.id} run={run_idx}/{runs} "
                f"arms={modes}"
            )
            arm_runs = run_task(
                task=task,
                arms=adapters,
                out_dir=out_dir,
                run_index=run_idx,
                max_turns=max_turns,
                pilot=pilot,
            )
            for r in arm_runs:
                tag = "[red]ERR[/red]" if r.arm_result.error else "[green]OK[/green]"
                scores = " ".join(
                    f"{c.name}={'n/a' if c.score is None else f'{c.score:.2f}'}"
                    for c in r.checks
                ) or "(no checks)"
                console.print(
                    f"  {tag} {r.arm_result.arm_name}: "
                    f"{len(r.arm_result.qa_turns)} Q&A, "
                    f"{len(r.arm_result.design)} design chars | {scores}"
                )
                drift = next(
                    (
                        e
                        for e in r.arm_result.raw_events
                        if isinstance(e, dict) and e.get("type") == "canon_drift_warning"
                    ),
                    None,
                )
                if drift:
                    issues = drift.get("issues", [])
                    console.print(
                        f"     [yellow]⚠ canon drift in answers ({len(issues)} issue(s)):[/yellow]"
                    )
                    for it in issues[:3]:
                        console.print(
                            f"        - {it.get('canon_field', '?')}: "
                            f"{it.get('rationale', '')[:160]}"
                        )


@main.command()
@click.option(
    "--results",
    "results_dir",
    default="results",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--out-md",
    default="results/report.md",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--out-json",
    default="results/report.json",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--cost-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML file mapping {task_id: {run_index: {arm: usd}}}.",
)
def report(results_dir: Path, out_md: Path, out_json: Path, cost_file: Path | None) -> None:
    """Aggregate results into a markdown + JSON report."""
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = build_report(results_dir, out_md, out_json, cost_file=cost_file)
    if not payload:
        console.print("[yellow]No runs found in results dir.[/yellow]")
        return
    console.print(f"[green]Report written:[/green] {out_md} / {out_json}")
    for arm, info in payload.get("arms", {}).items():
        console.print(
            f"  {arm}: n={info['n_runs']} errors={info['error_count']} "
            f"cost={info.get('cost_total') or '—'}"
        )


if __name__ == "__main__":
    main()
