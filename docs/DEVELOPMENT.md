# Development Guide (V3.1)

This guide describes how to work on DiaSync Memory locally with confidence.

## 1. Repository Surface

Primary areas:

- `.opencode/skills/diasync-memory/`: publishable skill package.
- `.opencode/skills/diasync-memory/scripts/memoryctl.py`: runtime source of truth.
- `docs/`: architecture and protocol documentation.
- `.memory/`: runtime data root (generated, not source-controlled).

Avoid editing generated/runtime locations directly unless you are intentionally testing
runtime behavior.

## 2. Prerequisites

- Python 3.10+
- Shell access from repository root
- No extra Python dependencies required for core runtime

## 3. Fast Local Sanity Check

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py --help
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
```

## 4. Build / Lint / Test Baseline

There is no formal build or linter pipeline in this repository.

Use these checks as gates:

```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```

Useful operational smoke checks:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py stats
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --dry-run
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --dry-run
```

## 5. Running A Single Test

Because no unit-test runner is committed, run one behavior-level command and then strict
validation against an isolated root.

Single behavior test:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --root .memory_test --scope project:demo --project demo --instance-id ins-test --summary "smoke capture" --dry-run
```

Validation for the same root:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --root .memory_test --strict
```

## 6. Typical End-To-End Flow

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope project:demo --instance-id ins-main --summary "Record high-value observation"
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope project:demo --instance-id ins-main
python .opencode/skills/diasync-memory/scripts/memoryctl.py publish --scope project:demo --instance-id ins-main --summary "Share stable project knowledge"
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --scope project:demo --reindex
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project demo --summary "Session completed"
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id ins-main --scope project:demo
```

For full scenario scripts, use:

- `.opencode/skills/diasync-memory/examples/DEMO_COMMANDS.md`
- `.opencode/skills/diasync-memory/examples/AUTONOMOUS_SESSION.md`

## 7. Code Change Expectations

When modifying `memoryctl.py`:

- Keep outputs machine-readable JSON.
- Preserve append-only ledger semantics.
- Keep hashes/timestamps consistent with current behavior.
- Add or update schema validation for new fields.
- Maintain `--dry-run` behavior for side-effectful commands.

## 8. Documentation Sync Requirements

If command flags, behavior, or data semantics change, also update:

- `docs/MEMORYCTL_CLI_SPEC.md`
- `docs/MEMORY_FORMAT_SPEC.md`
- `.opencode/skills/diasync-memory/references/COMMANDS.md`
- `.opencode/skills/diasync-memory/references/PROACTIVE_CADENCE.md`
- `.opencode/skills/diasync-memory/references/MEMORY_DEBT.md`
- `.opencode/skills/diasync-memory/references/COMPLEXITY_RADAR.md`
- relevant examples in `.opencode/skills/diasync-memory/examples/`

## 9. Release-Ready Checklist

Before opening a release PR:

```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --dry-run
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --dry-run
```

Then verify `docs/` reflects the implemented behavior.

## 10. Autonomous Evolution Loop

To run the skill-driven autonomous memory evolution framework:

```bash
python evolution.py --config evo/config.default.json --max-epochs 20
```

With live progress events:

```bash
python evolution.py --config evo/config.default.json --max-epochs 20 --heartbeat-seconds 15
```

Progress is also written to `artifacts/evolution/<run_id>/progress.jsonl`.

Continuous loop until stop signal:

```bash
python evolution.py --config evo/config.default.json --continuous --max-epochs 0
```

For evaluation-only mode (no mutation application):

```bash
python evolution.py --config evo/config.default.json --dry-run --disable-mutation
```

Fast smoke wiring check:

```bash
python evolution.py --config evo/config.smoke.json --dry-run --disable-mutation --max-epochs 0
```

Default config sets `runner_fallback_only: false` to keep real autonomous pressure in
the loop. Enable `runner_fallback_only: true` only when you need deterministic
stabilization for debugging.

Acceptance now includes objective gates tied to the end state (fallback dependency,
diachronic/synchronic/skill-alignment trends), so candidates without real objective
progress are rejected even when they pass basic hard gates.

If runner providers are blocked (for example quota/auth failures), evo records explicit
provider-block metrics and can stop with `provider-blocked` instead of spinning through
non-actionable fallback-only epochs.

Runner provider invocations now apply uniform retry (3 retries with backoff) before
classifying a turn as provider-blocked.

Default provider-block stop policy uses full-snapshot threshold (`1.0`) with one
grace snapshot, so transient pool instability does not terminate the run immediately.

When `continue_on_provider_blocked` is enabled, evo enters degraded mode and keeps
mutation pressure active with a bounded provisional-acceptance policy. Candidate evidence
is recorded in `candidate-bank.json` for later high-confidence confirmation.

Final run summary includes provisional state telemetry (`provisional_accepts`,
`provisional_pending`, `provisional_confirmations`) to show whether degraded-mode
acceptances have been confirmed after provider recovery.

Runner applies provider-fast-fallback per scenario: after hard provider blockage is
detected, remaining turns switch to deterministic memoryctl fallback to avoid retry storms
while preserving iterative learning pressure.

If Judge JSON remains unreliable in your environment, the framework uses compact AI fallback
and then deterministic fallback scoring to keep the loop operational.

Artifacts are written under `artifacts/evolution/<run_id>/`.
