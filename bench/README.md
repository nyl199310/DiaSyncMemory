# Bench Scenarios

This directory stores scenario DSL files used by `python evolution.py`.

- `train/`: scenarios available to both evaluator and mutator loops.
- `holdout/`: scenarios used for anti-overfitting gates.

Each scenario is filesystem-native and skill-driven:
- no vector retrieval assumptions,
- no hidden orchestration hooks,
- realistic multi-session and multi-instance behaviors.

Scenario variables available in turn templates:

- `{memory_root}`
- `{project}`
- `{scope}`
- `{scenario_id}`
- `{scenario_title}`

Turn directives:

- Prefix a turn with `[[NEW_SESSION]]` to force a new OpenCode session boundary.
