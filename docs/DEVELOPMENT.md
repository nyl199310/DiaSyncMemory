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
