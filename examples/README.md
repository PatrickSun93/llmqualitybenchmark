# `examples/` — pre-generated ShipFlow output

Drop pre-run ShipFlow output trees here so the harness can score them
offline (instead of spawning ShipFlow live every run).

## Layout

```
examples/
└── <task_id>/
    ├── main/
    │   └── docs/shipflow/
    │       ├── discovery/<slug>/
    │       │   ├── seed.md
    │       │   ├── questions.md
    │       │   ├── answers.md
    │       │   └── dialogue-*.md
    │       └── briefs/BRIEF-001-<slug>.md
    └── mono/
        └── docs/shipflow/...
```

`<task_id>` matches the `id:` in the corresponding `tasks/<task_id>.yaml`.
`main/` and `mono/` correspond to the two ShipFlow branches.

## How to populate

For each (task, arm), run ShipFlow once by hand and copy the output:

```bash
# From a fresh repo
cd /tmp/scratch-main && git init
claude   # interactive
> /sf-init
> /sf-discover "<the same idea you put in your task YAML>"
# answer questions consistent with the canon in your task YAML
> /sf-brief

# Copy the resulting docs/shipflow/ tree into examples/<task_id>/main/
mkdir -p ../llmqualitybenchmark/examples/<task_id>/main
cp -r docs ../llmqualitybenchmark/examples/<task_id>/main/

# Repeat in a separate scratch dir on the experiment/mono-agent branch
# of the ShipFlow plugin → copy into examples/<task_id>/mono/
```

## Canon consistency

The hand-typed answers in `answers.md` MUST match the constraints in
`tasks/<task_id>.yaml::canon` — else scores are noise from your own
inconsistency, not from ShipFlow.

The harness runs a single Haiku check at scoring time and prints a
warning if your answers contradict the canon. Disable with
`--no-verify-examples` once you've vetted the example.

## Why offline mode

- Reproducible: `git pull` and re-score gives the same numbers forever.
- Cheap: rubric tweaks no longer require re-running ShipFlow.
- Realistic: real human answers, not the User Simulator's approximation.

The trade-off is one-time setup cost: you must run ShipFlow once per
(task, arm). After that, scoring is free.
