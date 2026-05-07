"""Aggregate per-run summaries into a benchmark report.

Layer 1: one-line conclusion per arm against the appropriate baseline.
Layer 2: per-dimension table — split into Intrinsic (capability-blind) and
         Q&A-Mediated groups so bare Vanilla isn't penalized for not asking
         questions on dimensions it has no facility for.
Layer 3: representative examples — deferred to v2.

Cost-adjusted lift: optional. Pass --cost-file <path> to a YAML mapping
{ "<task_id>": { "<run_index>": { "<arm>": <usd_float>, ... } } } and the report
will include cost columns and a Pareto-friendly summary.

Baseline strategy:
  - Intrinsic dimensions:    baseline = `vanilla` (all arms compete fairly).
  - Q&A-Mediated dimensions: baseline = `vanilla-with-canon` (the upper bound
                                        for plain Claude with perfect context).
                                        Bare `vanilla` is shown but its score
                                        on these dimensions reflects the
                                        absence of Q&A, not a quality deficit.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Bare baseline (no plugin, no canon).
BARE_BASELINE_ARM = "vanilla"
# Fairness baseline for Q&A-mediated dimensions.
FAIR_BASELINE_ARM = "vanilla-with-canon"

# Dimensions that don't depend on Q&A capability — Vanilla can compete here.
INTRINSIC_DIMENSIONS = [
    "decision_density",
    "internal_consistency",
    "scope_discipline",
]

# Dimensions whose score depends on whether the arm did Q&A. For bare Vanilla
# these are typically lower not because the arm is worse but because it has
# no Q&A facility. Compare against vanilla-with-canon to see real lift.
QA_MEDIATED_DIMENSIONS = [
    "canon_consistency",
    "critical_decision_coverage",
    "question_coverage",
    "question_quality",
]


@dataclass
class ArmAggregate:
    arm: str
    n_runs: int
    score_means: dict[str, float]
    score_stds: dict[str, float]
    cost_total: float | None = None
    error_count: int = 0


def _load_summaries(results_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(results_dir.rglob("summary.json"))]


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
                if score is None:
                    # N/A — exclude from aggregation.
                    continue
                by_arm[arm][dim].append(float(score))
            arm_cost = (
                costs.get(task_id, {}).get(run_index, {}).get(arm) if costs else None
            )
            if arm_cost is not None:
                cost_total[arm] += float(arm_cost)
                cost_seen[arm] = True

    out: dict[str, ArmAggregate] = {}
    # Ensure every arm seen in any summary is represented, even if all dims
    # were N/A.
    seen_arms = {arm_entry["name"] for s in summaries for arm_entry in s["arms"]}
    for arm in seen_arms:
        dim_scores = by_arm.get(arm, {})
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
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"1st": 0, "2nd": 0, "3rd_or_worse": 0})
    )
    for s in summaries:
        for dim, ranks in (s.get("pairwise_ranks") or {}).items():
            for arm, rank in ranks.items():
                bucket = "1st" if rank == 1 else "2nd" if rank == 2 else "3rd_or_worse"
                out[dim][arm][bucket] += 1
    return out


def _format_lift(arm_value: float | None, baseline_value: float | None) -> str:
    if arm_value is None or baseline_value is None:
        return "—"
    delta = arm_value - baseline_value
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f}"


def _render_dimension_table(
    title: str,
    dimensions: list[str],
    aggregates: dict[str, ArmAggregate],
    arm_order: list[str],
    baseline_arm: str,
    note: str,
) -> list[str]:
    """Render one Layer-2 sub-table (intrinsic or Q&A-mediated)."""
    present = [d for d in dimensions if any(d in a.score_means for a in aggregates.values())]
    if not present:
        return []

    lines: list[str] = []
    lines.append(f"### {title}\n")
    if note:
        lines.append(f"_{note}_\n")

    other_arms = [a for a in arm_order if a != baseline_arm]
    header = ["dimension", *arm_order, *[f"lift({a})" for a in other_arms]]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    baseline = aggregates.get(baseline_arm)
    for dim in present:
        row = [f"`{dim}`"]
        for arm in arm_order:
            agg = aggregates.get(arm)
            mean = agg.score_means.get(dim) if agg else None
            std = agg.score_stds.get(dim, 0.0) if agg else 0.0
            row.append(f"{mean:.2f} ± {std:.2f}" if mean is not None else "n/a")
        base_mean = baseline.score_means.get(dim) if baseline else None
        for arm in other_arms:
            agg = aggregates.get(arm)
            arm_mean = agg.score_means.get(dim) if agg else None
            row.append(_format_lift(arm_mean, base_mean))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def render_markdown(
    summaries: list[dict],
    aggregates: dict[str, ArmAggregate],
    pairwise: dict[str, dict[str, dict[str, int]]],
) -> str:
    lines: list[str] = []
    n_tasks = len({s["task_id"] for s in summaries})

    # Stable arm display order.
    preferred = ["vanilla", "vanilla-with-canon", "main", "mono"]
    seen = list(aggregates.keys())
    arm_order = [a for a in preferred if a in seen] + [a for a in seen if a not in preferred]

    lines.append("# Quality Benchmark Report\n")
    lines.append(
        f"_{n_tasks} task(s), {len(summaries)} per-task run(s), arms: "
        f"{', '.join(arm_order)}_\n"
    )

    # Layer 1 — biggest lifts per arm against the appropriate baseline
    bare = aggregates.get(BARE_BASELINE_ARM)
    fair = aggregates.get(FAIR_BASELINE_ARM)
    if bare or fair:
        bullets: list[str] = []
        for arm in arm_order:
            if arm in (BARE_BASELINE_ARM, FAIR_BASELINE_ARM):
                continue
            agg = aggregates.get(arm)
            if not agg:
                continue
            best_dim = None
            best_lift = float("-inf")
            for dim, mean in agg.score_means.items():
                base_arm = (
                    FAIR_BASELINE_ARM if dim in QA_MEDIATED_DIMENSIONS else BARE_BASELINE_ARM
                )
                base = aggregates.get(base_arm)
                if not base:
                    continue
                base_mean = base.score_means.get(dim)
                if base_mean is None:
                    continue
                lift = mean - base_mean
                if lift > best_lift:
                    best_lift, best_dim = lift, dim
            if best_dim is not None:
                base_arm = (
                    FAIR_BASELINE_ARM
                    if best_dim in QA_MEDIATED_DIMENSIONS
                    else BARE_BASELINE_ARM
                )
                bullets.append(
                    f"- **{arm}** strongest lift over `{base_arm}`: "
                    f"`{best_dim}` ({best_lift:+.2f})"
                )
        if bullets:
            lines.append("## Layer 1 — Headline\n")
            lines.extend(bullets)
            lines.append("")

    # Layer 2 — per-dimension tables, grouped
    lines.append("## Layer 2 — Per-dimension scores\n")
    lines.append(
        "Dimensions are grouped to neutralize structural bias against bare Vanilla. "
        "Intrinsic dimensions are capability-blind — all arms compete fairly. "
        "Q&A-mediated dimensions depend on whether the arm performed Q&A; the fair "
        "baseline is `vanilla-with-canon` (Vanilla given the canon directly), not "
        "bare `vanilla`. N/A means the dimension does not apply to that arm.\n"
    )

    lines.extend(
        _render_dimension_table(
            title="Intrinsic Quality (capability-blind)",
            dimensions=INTRINSIC_DIMENSIONS,
            aggregates=aggregates,
            arm_order=arm_order,
            baseline_arm=BARE_BASELINE_ARM,
            note="Lift is over `vanilla`. All arms compete on equal footing.",
        )
    )
    lines.extend(
        _render_dimension_table(
            title="Q&A-Mediated Quality (depends on Q&A capability)",
            dimensions=QA_MEDIATED_DIMENSIONS,
            aggregates=aggregates,
            arm_order=arm_order,
            baseline_arm=FAIR_BASELINE_ARM,
            note=(
                "Lift is over `vanilla-with-canon` (the fair upper bound for "
                "plain Claude with perfect context). Bare `vanilla` is shown "
                "but its scores reflect absence of Q&A, not design ability."
            ),
        )
    )

    if pairwise:
        lines.append("## Pairwise Tournament\n")
        lines.append(
            "_Per dimension, the judge ranks all eligible arms. Arms ineligible "
            "for a dimension (N/A) are excluded from that ranking._\n"
        )
        lines.append("| dimension | " + " | ".join(arm_order) + " |")
        lines.append("|" + "|".join(["---"] * (1 + len(arm_order))) + "|")
        for dim in sorted(pairwise.keys()):
            row = [f"`{dim}`"]
            for arm in arm_order:
                buckets = pairwise[dim].get(arm)
                if buckets is None:
                    row.append("n/a")
                else:
                    row.append(
                        f"1st:{buckets['1st']} 2nd:{buckets['2nd']} "
                        f"3+:{buckets['3rd_or_worse']}"
                    )
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    if any(a.cost_total is not None for a in aggregates.values()):
        lines.append("## Cost\n")
        lines.append("| arm | total cost | runs | error count |")
        lines.append("|---|---|---|---|")
        for arm in arm_order:
            agg = aggregates.get(arm)
            if not agg:
                continue
            cost = f"${agg.cost_total:.2f}" if agg.cost_total is not None else "—"
            lines.append(f"| {arm} | {cost} | {agg.n_runs} | {agg.error_count} |")
        lines.append("")

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
        "dimension_groups": {
            "intrinsic": INTRINSIC_DIMENSIONS,
            "qa_mediated": QA_MEDIATED_DIMENSIONS,
        },
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload
