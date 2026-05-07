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

```bash
# Install
pip install -e .

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run pilot (1 task, 3 arms, 1 run)
qualitybench run --task tasks/01_habit_tracker.yaml --pilot

# Full v1 run
qualitybench run --tasks tasks/ --runs 3
```

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
