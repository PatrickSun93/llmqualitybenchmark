# LLM Quality Benchmark

A quality benchmark for Claude Code phase-gated multi-agent workflow plugins.

Measures **plugin lift over baseline** rather than absolute model quality.
Compares 3 arms on open-ended design tasks:

- **Vanilla**: bare `claude -p`, no plugin
- **ShipFlow Main**: 22 specialized agents (role in system prompt)
- **ShipFlow Mono**: 1 generic agent + role-as-content (experiment branch)

Stops at design phase — does not produce code.

See [SPEC.md](./SPEC.md) for the full design and [DESIGN_NOTES.md](./DESIGN_NOTES.md) for the reasoning.

## Honest disclaimer

> This benchmark does not measure whether designs are *good* in any absolute sense.
> It measures whether designs are *well-formed*: internally consistent, faithful to
> elicited user constraints, decision-dense rather than handwaving, traceable to
> premises. A high score means a system reliably produces well-formed designs;
> it does not mean those designs are the ones a particular user would have chosen.

## Quick start

All LLM calls route through `claude -p` — i.e. your **Claude Code subscription**.
No API key needed. Quota uses per-message budget instead of per-token billing.

```bash
# 1. Install
pip install -e .

# 2. Make sure claude CLI is logged in (once)
claude login

# 3. Set up ShipFlow worktrees (only if running 'main' / 'mono' arms)
git clone https://github.com/PatrickSun93/shipflow ~/shipflow
git -C ~/shipflow worktree add ~/shipflow-mono experiment/mono-agent
export SHIPFLOW_MAIN_PATH=~/shipflow
export SHIPFLOW_MONO_PATH=~/shipflow-mono

# 4. Pilot (Vanilla only — cheap smoke test)
qualitybench run --task tasks/01_habit_tracker.yaml --arms vanilla --pilot

# 5. Full 3-arm pilot
qualitybench run --task tasks/01_habit_tracker.yaml --pilot

# 6. Full v1 run
qualitybench run --tasks tasks/ --runs 3

# 7. Generate report (paste cost numbers from /cost into costs.example.yaml first)
qualitybench report --cost-file costs.example.yaml
```

### Quota notes

A pilot run uses roughly 30 messages of subscription quota per task (3 arms ×
~10 calls each between Q&A, design generation, checks, judges). Max plan caps
out around 200 messages per 5-hour window — so 6–7 task pilots fit per window
before reset.

### Offline mode (recommended)

Live ShipFlow invocation is slow and chews through quota. Better workflow:

1. Run ShipFlow once per (task, branch) by hand and copy the `docs/shipflow/`
   output into `examples/<task_id>/{main,mono}/`. See [`examples/README.md`](./examples/README.md).
2. Pass `--examples-dir examples/` — arms `main`/`mono` will score those
   pre-generated files instead of running ShipFlow live.
3. Tweak rubrics, re-score in seconds. Check into git for reproducibility.

```bash
qualitybench run \
  --tasks tasks/ \
  --arms vanilla,vanilla-with-canon,main,mono \
  --examples-dir examples/ \
  --runs 3
```

The harness automatically falls back to live mode for any (task, arm) that's
missing under `examples/`. A single Haiku check at scoring time verifies that
your hand-typed answers in `answers.md` are consistent with the canon —
warnings printed inline.

## Layout

```
.
├── SPEC.md              # build target
├── DESIGN_NOTES.md      # reasoning & methodology
├── src/qualitybench/    # harness implementation
│   ├── schema.py        # Task / Canon Pydantic models
│   ├── simulator.py     # User Simulator
│   ├── arms/            # Vanilla / Main / Mono adapters
│   ├── checks/          # deterministic checks
│   ├── judge.py         # pairwise tournament + persona ensemble
│   ├── report.py        # markdown + JSON output
│   └── cli.py           # entry point
├── tasks/               # task YAML manifests
├── rubrics/             # judge rubric prompts
└── results/             # gitignored, run outputs
```
