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

## 4.1 Runner Safety Mode

Default config keeps autonomous runner behavior enabled (`runner_fallback_only: false`):

- free-form agent execution remains the primary source of adaptation pressure,
- deterministic fallback is still available as a safety net when execution degrades.

If you need deterministic stabilization for debugging, set `runner_fallback_only` to `true`:

- scenario execution is enforced through filesystem-native `memoryctl` commands,
- workspace-edit side effects from autonomous tool usage are prevented,
- multi-session directives are still honored via isolated fallback instance lifecycles.

## 5. Autonomous Epoch Loop

Each epoch runs this closed loop:

1. Synthesize fresh train/holdout scenarios from recent train failures.
2. Evaluate control baseline on sampled or full scenario batches.
3. Generate mutation proposal from control failure profile.
4. Apply mutation in bounded allow-list scope.
5. Run quality gates (plus runtime-lane gates when runtime files are touched).
6. Evaluate candidate on the same decision batch.
7. Accept candidate only when hard gates pass, score-improvement policy is met, and
   candidate introduces a meaningful diff in allowed skill/runtime evolution surfaces.
8. Otherwise rollback automatically.

Meaningful diff is evaluated against active evolution surfaces (configured `skill_paths`
plus runtime-lane paths), not arbitrary docs that the runner does not hydrate.

When provider instability blocks autonomous validation, evo now enters a degraded
provider mode instead of dropping mutation pressure immediately:

- mutation proposals are still generated and evaluated,
- candidate evidence is tracked in a run-local candidate bank,
- and provisional acceptance is allowed only with bounded policy (hydrated-surface diff,
  failure-alignment score, objective non-regression, and per-run acceptance cap).

Provisional state is tracked explicitly (`provisional_pending`) and can be marked confirmed
once provider blockage clears and confirmation thresholds are met (validation confidence,
provider-blocked rate, and hard-pass rate).

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

Runner fallback dependency is explicitly penalized in scoring (stronger penalty in
fallback-only mode) so deterministic fallback cannot dominate optimization indefinitely.

Decision policy also enforces objective gates tied to the end state:

- fallback dependency must not increase beyond configured tolerance,
- provider-blocked executions (for example quota/auth failures) must not increase,
- core dimensions (`diachronic`, `synchronic`, `skill_alignment`) cannot regress beyond
  configured limits,
- and (by default) at least one core objective metric must improve before acceptance.

When provider blockage dominates snapshots, evo can stop with `provider-blocked`
to avoid wasting epochs on non-actionable fallback-only loops. Default policy uses
`provider_blocked_stop_rate=1.0` with one grace snapshot before stopping.

If `continue_on_provider_blocked` is enabled, evo keeps iterating in degraded mode and
records provisional decisions rather than terminating at the first sustained blockage.

Runner provider calls use uniform retry policy (3 retries with backoff) before
provider-block classification, to absorb unstable third-party API pools.

Runner also uses provider-fast-fallback: once hard provider blockage is detected for a
scenario, remaining turns are executed via deterministic memoryctl fallback to preserve
iteration cadence and reduce wasted retry churn.

Judge reliability policy:

- primary score comes from the Judge agent JSON payload,
- if Judge output is invalid/unusable, the framework requests compact AI fallback scoring,
- if Judge remains unreliable, a deterministic heuristic fallback keeps the loop operational.

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
