# Autonomous Memory Evolution Framework

This document defines the end-state-oriented framework behind `python evolution.py`.

Core intent: keep memory behavior improving autonomously without human-in-the-loop for every
iteration, while preserving correctness, auditability, and real-world robustness.

## 1. End State (Begin With The End)

The evolving system should converge toward an agent memory mechanism that:

- preserves continuity across long time horizons (diachronic complexity),
- remains conflict-safe under concurrent pressure (synchronic complexity),
- closes governance loops (`diagnose` + `optimize`) proactively,
- and stays filesystem-native, inspectable, and replayable at all times.

Primary execution entrypoint:

```bash
python evolution.py --config evo/config.default.json --max-epochs 200
```

Continuous mode (stop manually via `.evo/STOP`):

```bash
python evolution.py --config evo/config.default.json --continuous --max-epochs 0
```

## 2. First-Principles Constraints

1. **External evidence over self-claims**
   - Every epoch is judged by artifacts (`session-export`, command trace, memory probe outputs).
2. **Skill-driven autonomy over hardcoded orchestration**
   - Runner behavior is guided by the skill manifest and references.
3. **Filesystem-native only**
   - No vector retrieval dependency; all state is verifiable from files and ledgers.
4. **Reality stress over demo comfort**
   - Scenarios include interruptions, contention, and release-pressure conditions.
5. **Closed-loop mutation**
   - Candidate changes are applied, gated, scored, and accepted/rejected automatically.

## 3. Core Modules

- `evolution.py`: CLI entrypoint and runtime overrides.
- `evo/orchestrator.py`: autonomous epoch loop, gates, decision, rollback.
- `evo/runner.py`: multi-turn and multi-session scenario execution.
- `evo/synthesizer.py`: AI-generated dynamic scenario synthesis per epoch.
- `evo/evaluator.py`: AI judge + machine penalties + hard pass integration.
- `evo/mutator.py`: bounded file mutations with allow/deny guardrails.
- `evo/probe.py`: strict memory integrity and governance probe commands.
- `evo/opencode_client.py`: OpenCode run/export integration.

Prompt contracts:

- `evo/prompts/runner_contract.md`
- `evo/prompts/judge_contract.md`
- `evo/prompts/mutator_contract.md`
- `evo/prompts/scenario_synthesizer_contract.md`

## 4. Role Separation

- **Runner Agent**: executes behavior under scenario constraints.
- **Judge Agent**: scores independently from execution context.
- **Mutator Agent**: proposes minimal edits from failure evidence.
- **Synthesizer Agent**: generates new realistic stress scenarios each epoch.

Role separation prevents single-session self-confirming loops.

## 5. Autonomous Epoch Loop

Each epoch runs this closed loop:

1. Synthesize fresh train/holdout scenarios from recent train failures.
2. Evaluate control baseline on sampled or full scenario batches.
3. Generate mutation proposal from control failure profile.
4. Apply mutation in bounded allow-list scope.
5. Run quality gates (plus runtime-lane gates when runtime files are touched).
6. Evaluate candidate on the same decision batch.
7. Accept candidate only when hard gates pass and score-improvement policy is met.
8. Otherwise rollback automatically.

All artifacts are written under `artifacts/evolution/<run_id>/`.

## 6. Dynamic Scenario Synthesis

Scenario synthesis is epoch-native, not static-only:

- `synthesis.per_epoch_train` and `synthesis.per_epoch_holdout` control counts.
- Generated scenarios are normalized and bounded (turn count, difficulty, complexity mode).
- Synthesis context includes recent train failures and existing scenario corpus.

This reduces overfitting to a fixed benchmark set.

## 7. Skill Hydration Hard Gate

Skill alignment is enforced behaviorally:

- Runner prompts require skill reads at each new session boundary.
- Machine checks verify required skill paths were actually read.
- Missing required hydration reads can trigger hard failure.

Configuration is in `skill_hydration` inside `evo/config.default.json`.

## 8. Runtime Evolution Lane

Runtime lane allows autonomous mutation of
`.opencode/skills/diasync-memory/scripts/memoryctl.py` with stricter controls:

- explicit runtime path allow-list,
- extra gate commands,
- optional full-batch re-evaluation,
- stronger acceptance threshold (`runtime_lane.min_improvement`).

This supports end-to-end autonomous improvement while preserving safety.

## 9. Scoring and Decision

Judge dimensions:

- `diachronic`
- `synchronic`
- `governance`
- `realism`
- `skill_alignment`

Machine penalties cover concrete contract violations (for example, missing scenario root usage,
incomplete lifecycle closure, missing skill hydration). Hard integrity failures force fitness to
zero and reject candidate adoption.

## 10. Stop Conditions

Loop stops when any condition is met:

- stop file exists (`.evo/STOP`),
- max epochs reached (if configured),
- wall-time limit reached (if configured),
- max stagnation threshold reached (if configured).

## 11. Recommended Operation Modes

Full autonomous iteration:

```bash
python evolution.py --config evo/config.default.json --max-epochs 200
```

Live progress with periodic wait heartbeats:

```bash
python evolution.py --config evo/config.default.json --max-epochs 200 --heartbeat-seconds 15
```

Continuous daemon-like mode:

```bash
python evolution.py --config evo/config.default.json --continuous --max-epochs 0
```

Progress stream artifacts:

- stderr live progress lines
- `artifacts/evolution/<run_id>/progress.jsonl`

Evaluation-only mode:

```bash
python evolution.py --config evo/config.default.json --dry-run --disable-mutation
```
