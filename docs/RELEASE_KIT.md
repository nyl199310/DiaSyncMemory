# Release Kit

This document contains practical release assets for publishing `diasync-memory`.

## 1. Pre-Release Checklist

Before tagging a release:

```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --dry-run
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --dry-run
```

Also verify:

- `docs/` reflects current behavior.
- `.opencode/skills/diasync-memory/references/COMMANDS.md` is current.
- examples in `.opencode/skills/diasync-memory/examples/` still run.

## 2. Suggested Repository Names

- `diasync-memory-skill`
- `agent-diasync-memory`
- `diasync-memory-for-opencode`

## 3. GitHub About Copy

Short:

`Production-ready filesystem-native memory skill for AI coding agents with cross-session continuity, explicit multi-instance coordination, conflict-safe writes, and continuous health governance.`

Long:

`diasync-memory is a single integrated skill package for OpenCode-compatible agents. It combines deterministic append-only memory writes, transparent filesystem-native recall, explicit concurrency controls (streams, bus, reducer, lease, conflict), and a built-in governance loop (diagnose and optimize). Runtime state is agent-managed in hidden .memory.`

## 4. Suggested Topics

- `ai-agent`
- `agent-memory`
- `skills`
- `opencode`
- `filesystem`
- `jsonl`
- `multi-agent`
- `concurrency`
- `diasync-memory`

## 5. Release Notes Template

Title:

`v3.1.0 - Stable filesystem-native memory runtime for multi-instance agents`

Body:

```markdown
## Highlights
- Ships as one installable skill package: `diasync-memory`
- Uses deterministic append-only runtime operations in `scripts/memoryctl.py`
- Maintains hidden `.memory` lifecycle with automatic initialization
- Preserves filesystem-native recall via `Read`/`Grep`/`Glob`
- Includes operational governance loop (`diagnose` + `optimize`)

## Command Surface
- Lifecycle: `sync`, `attach`, `checkpoint`, `handoff`
- Knowledge flow: `capture`, `distill`, `publish`, `reduce`, `reconcile`
- Coordination and governance: `lease`, `agenda`, `hygiene`, `validate`, `diagnose`, `optimize`, `stats`

## Runtime Model
- Private per-instance streams
- Shared publish bus
- Deterministic reduction into views
- Conflict ledger + lease-based contention control
- Governance ledgers for findings, scorecards, plans, and executions
```

## 6. README Intro Snippet

```markdown
DiaSync Memory is a production-ready skill package that gives AI coding agents durable, auditable memory across sessions and instances. It keeps writes deterministic and append-only while preserving transparent filesystem-native recall.
```

## 7. Minimal Changelog Sections

Use these sections in each release:

- Added
- Changed
- Fixed
- Operational impact
- Upgrade notes

## 8. Artifact Boundary

If publishing only the skill package, include:

- `.opencode/skills/diasync-memory/SKILL.md`
- `.opencode/skills/diasync-memory/scripts/memoryctl.py`
- `.opencode/skills/diasync-memory/references/*.md`
- `.opencode/skills/diasync-memory/examples/*.md`

Exclude runtime/generated directories (`.memory/`, `venv/`, `node_modules/`).
