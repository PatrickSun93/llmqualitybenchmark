"""Aggregate per-run summaries into a benchmark report.

Layer 1: one-line conclusion comparing arms on the most informative dimensions.
Layer 2: per-dimension table — mean score per arm with lift over the Vanilla
         baseline, plus pairwise win-rate (best, middle, worst counts).
Layer 3: representative examples — deferred to v2.

Cost-adjusted lift: optional. Pass --cost-file <path> to a YAML mapping
{ "<task_id>": { "<run_index>": { "<arm>": <usd_float>, ... } } } and the report
will include cost columns and a Pareto-friendly summary.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

BASELINE_ARM = "vanilla"


@dataclass
class ArmAggregate:
    arm: str
    n_runs: int
    score_means: dict[str, float]
    score_stds: dict[str, float]
    cost_total: float | None = None
    error_count: int = 0


def _load_summaries(results_dir: Path) -> list[dict]:
    """Load every summary.json under results_dir."""
    return [
        json.loads(p.read_text())
        for p in sorted(results_dir.rglob("summary.json"))
    ]


def _load_costs(cost_file: Path | None) -> dict[str, dict[str, dict[str, float]]]:
    if cost_file is None:
        return {}
    with cost_file.open() as f:
        data = yaml.safe_load(f) or {}
    return data


def _aggregate(summaries: list[dict], costs: dict) -> dict[str, ArmAggregate]:
    by_arm: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    error_count: dict[str, int] = defaultdict(int)
    cost_total: dict[str, float] = defaultdict(float)
    cost_seen: dict[str, bool] = defaultdict(bool)

    for s in summaries:
        task_id = s["task_id"]
        run_index = str(s["run_index"])
        for arm_entry in s["arms"]:
            arm = arm_entry["name"]
            if arm_entry.get("error"):
                error_count[arm] += 1
            for dim, score in arm_entry.get("scores", {}).items():
                by_arm[arm][dim].append(float(score))
            arm_cost = (
                costs.get(task_id, {}).get(run_index, {}).get(arm)
                if costs
                else None
            )
            if arm_cost is not None:
                cost_total[arm] += float(arm_cost)
                cost_seen[arm] = True

    out: dict[str, ArmAggregate] = {}
    for arm, dim_scores in by_arm.items():
        means = {dim: statistics.fmean(vals) for dim, vals in dim_scores.items() if vals}
        stds = {
            dim: (statistics.pstdev(vals) if len(vals) >= 2 else 0.0)
            for dim, vals in dim_scores.items()
        }
        n = max((len(v) for v in dim_scores.values()), default=0)
        out[arm] = ArmAggregate(
            arm=arm,
            n_runs=n,
            score_means=means,
            score_stds=stds,
            cost_total=cost_total[arm] if cost_seen[arm] else None,
            error_count=error_count[arm],
        )
    return out


def _pairwise_winrates(summaries: list[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """Per dimension: count how often each arm placed 1st / 2nd / 3rd."""
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"1st": 0, "2nd": 0, "3rd_or_worse": 0})
    )
    for s in summaries:
        for dim, ranks in (s.get("pairwise_ranks") or {}).items():
            for arm, rank in ranks.items():
                bucket = "1st" if rank == 1 else "2nd" if rank == 2 else "3rd_or_worse"
                out[dim][arm][bucket] += 1
    return out


def _format_lift(arm_value: float, baseline_value: float | None) -> str:
    if baseline_value is None:
        return "—"
    delta = arm_value - baseline_value
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f}"


def render_markdown(
    summaries: list[dict],
    aggregates: dict[str, ArmAggregate],
    pairwise: dict[str, dict[str, dict[str, int]]],
) -> str:
    lines: list[str] = []
    n_tasks = len({s["task_id"] for s in summaries})
    arm_names = list(aggregates.keys())
    baseline = aggregates.get(BASELINE_ARM)

    # ---- Layer 1: one-line conclusions
    lines.append("# Quality Benchmark Report\n")
    lines.append(f"_{n_tasks} task(s), {len(summaries)} per-task run(s), arms: {', '.join(arm_names)}_\n")

    if baseline:
        bullets: list[str] = []
        for arm in arm_names:
            if arm == BASELINE_ARM:
                continue
            agg = aggregates[arm]
            best_dim = None
            best_lift = float("-inf")
            for dim, mean in agg.score_means.items():
                base_mean = baseline.score_means.get(dim)
                if base_mean is None:
                    continue
                lift = mean - base_mean
                if lift > best_lift:
                    best_lift, best_dim = lift, dim
            if best_dim is not None:
                bullets.append(
                    f"- **{arm}** strongest lift over {BASELINE_ARM}: "
                    f"`{best_dim}` (+{best_lift:.2f})"
                )
        if bullets:
            lines.append("## Layer 1 — Headline\n")
            lines.extend(bullets)
            lines.append("")

    # ---- Layer 2: per-dimension table
    lines.append("## Layer 2 — Per-dimension scores\n")
    all_dims = sorted({d for agg in aggregates.values() for d in agg.score_means})
    if all_dims:
        header_cols = ["dimension"] + arm_names
        if baseline:
            header_cols += [f"lift({a})" for a in arm_names if a != BASELINE_ARM]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for dim in all_dims:
            row = [f"`{dim}`"]
            for arm in arm_names:
                mean = aggregates[arm].score_means.get(dim)
                std = aggregates[arm].score_stds.get(dim, 0.0)
                row.append(f"{mean:.2f} ± {std:.2f}" if mean is not None else "—")
            if baseline:
                base_mean = baseline.score_means.get(dim)
                for arm in arm_names:
                    if arm == BASELINE_ARM:
                        continue
                    arm_mean = aggregates[arm].score_means.get(dim)
                    row.append(_format_lift(arm_mean, base_mean) if arm_mean is not None else "—")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    else:
        lines.append("_(no scores recorded — all runs may have errored or been pilot stubs)_\n")

    # ---- Pairwise tournament
    if pairwise:
        lines.append("## Pairwise Tournament\n")
        lines.append("| dimension | " + " | ".join(arm_names) + " |")
        lines.append("|" + "|".join(["---"] * (1 + len(arm_names))) + "|")
        for dim in sorted(pairwise.keys()):
            row = [f"`{dim}`"]
            for arm in arm_names:
                buckets = pairwise[dim].get(arm, {"1st": 0, "2nd": 0, "3rd_or_worse": 0})
                row.append(f"1st:{buckets['1st']} 2nd:{buckets['2nd']} 3+:{buckets['3rd_or_worse']}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # ---- Cost
    if any(a.cost_total is not None for a in aggregates.values()):
        lines.append("## Cost\n")
        lines.append("| arm | total cost | runs | error count |")
        lines.append("|---|---|---|---|")
        for arm, agg in aggregates.items():
            cost = f"${agg.cost_total:.2f}" if agg.cost_total is not None else "—"
            lines.append(f"| {arm} | {cost} | {agg.n_runs} | {agg.error_count} |")
        lines.append("")

        if baseline and baseline.cost_total:
            lines.append("### Cost-adjusted lift (over vanilla)\n")
            lines.append("| dimension | " + " | ".join(
                a for a in arm_names if a != BASELINE_ARM
            ) + " |")
            lines.append("|" + "|".join(["---"] * (1 + sum(1 for a in arm_names if a != BASELINE_ARM))) + "|")
            for dim in all_dims:
                base_mean = baseline.score_means.get(dim)
                if base_mean is None:
                    continue
                row = [f"`{dim}`"]
                for arm in arm_names:
                    if arm == BASELINE_ARM:
                        continue
                    agg = aggregates[arm]
                    arm_mean = agg.score_means.get(dim)
                    if arm_mean is None or not agg.cost_total or not baseline.cost_total:
                        row.append("—")
                        continue
                    lift = arm_mean - base_mean
                    cost_mult = agg.cost_total / baseline.cost_total
                    row.append(f"{lift:+.2f} / {cost_mult:.1f}x = {lift / cost_mult:+.3f}")
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

    # ---- Honest disclaimer
    lines.append("---")
    lines.append(
        "> _This benchmark measures whether designs are well-formed (internally "
        "consistent, faithful to elicited constraints, decision-dense, traceable). "
        "It does not measure whether designs are subjectively good. See SPEC §15._"
    )
    return "\n".join(lines)


def build_report(
    results_dir: Path,
    out_md: Path,
    out_json: Path,
    cost_file: Path | None = None,
) -> dict[str, Any]:
    summaries = _load_summaries(results_dir)
    if not summaries:
        out_md.write_text("# Quality Benchmark Report\n\n_No runs found._\n")
        out_json.write_text("{}")
        return {}

    costs = _load_costs(cost_file)
    aggregates = _aggregate(summaries, costs)
    pairwise = _pairwise_winrates(summaries)

    md = render_markdown(summaries, aggregates, pairwise)
    out_md.write_text(md)

    payload = {
        "n_summaries": len(summaries),
        "arms": {
            arm: {
                "n_runs": agg.n_runs,
                "score_means": agg.score_means,
                "score_stds": agg.score_stds,
                "cost_total": agg.cost_total,
                "error_count": agg.error_count,
            }
            for arm, agg in aggregates.items()
        },
        "pairwise": pairwise,
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload
