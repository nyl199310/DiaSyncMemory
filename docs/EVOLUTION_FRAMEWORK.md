# Autonomous Memory Evolution Framework

This document defines a skill-first, filesystem-native framework for autonomous iteration of
memory behavior quality.

Primary entrypoint:

```bash
python evolution.py --config evo/config.default.json --max-epochs 50
```

## 1. End State (Begin With The End)

After enough epochs, the evolving agent should reliably:

- preserve continuity over long time horizons (diachronic complexity),
- coordinate safely under concurrent pressure (synchronic complexity),
- expose and resolve contention explicitly (never silent overwrite),
- maintain governance health (`diagnose` + `optimize`) without micromanagement,
- and keep all behavior auditable from filesystem artifacts.

## 2. First-Principles Constraints

1. **External truth over self-claims**
   - Scores and pass/fail decisions must be backed by artifacts and independent judging.
2. **Skill-driven behavior over hardcoded hooks**
   - Runtime behavior is guided by skill references, not brittle fixed scripts.
3. **Filesystem-native memory only**
   - No vector retrieval assumptions; all memory evidence remains file-auditable.
4. **Real-world robustness over demo optimization**
   - Scenario design stresses interruptions, drift, contention, and pressure conditions.

## 3. Architecture

Framework modules:

- `evolution.py`: CLI entrypoint.
- `evo/orchestrator.py`: epoch loop and accept/reject logic.
- `evo/runner.py`: executes scenario conversations via `opencode run`.
- `evo/probe.py`: runs `memoryctl` integrity/governance probes.
- `evo/evaluator.py`: independent AI judging + machine penalties.
- `evo/mutator.py`: proposes and applies bounded text mutations.
- `evo/scenarios.py`: scenario loading, curriculum batch selection, rendering.
- `evo/opencode_client.py`: structured OpenCode session operations.

Prompt contracts:

- `evo/prompts/runner_contract.md`
- `evo/prompts/judge_contract.md`
- `evo/prompts/mutator_contract.md`

Scenarios:

- `bench/scenarios/train/*.json`
- `bench/scenarios/holdout/*.json`

## 4. Agent Roles (Separated)

- **Runner Agent**: executes scenarios and produces behavior traces.
- **Judge Agent**: independently scores behavior against skill principles.
- **Mutator Agent**: proposes minimal, bounded edits from failure evidence.

Role separation prevents single-session self-confirmation loops.

## 5. Epoch Loop

Each epoch:

1. Select scenario batches (`train` + `holdout`) with curriculum pacing.
2. Run each scenario in isolated memory roots under `.memory_evolution/<run>/<epoch>/...`.
3. Export OpenCode sessions and command traces.
4. Probe each scenario root with:
   - `validate --strict`
   - `diagnose --dry-run`
   - `optimize --dry-run`
   - `stats`
5. Judge each run through an independent OpenCode scoring session.
6. Aggregate fitness and hard-pass rates.
7. Generate a bounded mutation proposal.
8. Apply proposal, run quality gates, and evaluate candidate.
9. Accept only if:
   - hard gates stay clean,
   - holdout does not regress,
   - and score improves above threshold.

## 6. Scoring Model (AI-Led, Artifact-Grounded)

Scoring dimensions:

- `diachronic`
- `synchronic`
- `governance`
- `realism`
- `skill_alignment`

Judge returns strict JSON. Framework then applies machine penalties for concrete issues
(for example, missing scenario-specific `--root` usage or incomplete lifecycle closure).

Hard gate failures force scenario fitness to zero.

## 7. Mutation System

Supported mutation ops:

- `replace_text`
- `insert_after`
- `insert_before`
- `append_text`
- `write_file`

Mutations are constrained by allow/deny path policy (`evo/config.default.json`).

Default policy prioritizes:

- prompt and scenario evolution,
- skill/reference updates,
- documentation alignment,

while denying runtime/generated zones like `.memory/`, `venv/`, and `.opencode/node_modules/`.

## 8. Realism and Saturation Strategy

Scenario corpus intentionally includes:

- interruption-heavy continuity flows,
- concurrent contention and reconciliation,
- mixed governance recovery under pressure,
- holdout stress tests to catch overfitting.

This design favors realistic failure discovery over artificial benchmark inflation.

## 9. Safety and Stop Conditions

The loop stops when any condition is met:

- `--max-epochs` reached,
- stagnation threshold reached,
- stop file exists (`.evo/STOP`),
- or manual interruption.

Every epoch writes artifacts under `artifacts/evolution/<run_id>/` for replay and audit.

## 10. Operating Notes

- Use `--dry-run` to evaluate without applying mutations.
- Use `--disable-mutation` to perform scoring-only runs.
- Tune scenario difficulty and batch size in `evo/config.default.json`.
- Keep skill references current; they are first-class evolution inputs.
