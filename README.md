# DiaSync Memory

> Filesystem-native long-term memory for AI agents and assistants.

DiaSync Memory is an open-source memory runtime (plus OpenCode skill package) that helps
agents keep context across sessions, coordinate concurrent instances, and preserve a fully
auditable write history.

If you are searching for terms like **AI agent memory**, **long-term memory for autonomous
agents**, **multi-agent memory synchronization**, or **append-only memory for LLM agents**,
this repository is built for that problem space.

## What This Project Is (Quick Summary)

- **Type:** Python CLI + Markdown protocol docs.
- **Runtime entrypoint:** `.opencode/skills/diasync-memory/scripts/memoryctl.py`.
- **Default data root:** `.memory/` (auto-initialized).
- **Storage model:** JSONL ledgers + Markdown capsules.
- **Core property:** deterministic append-only writes with conflict visibility.

## Why DiaSync Memory

- Deterministic, append-only write path for traceability and replay.
- Filesystem-native recall (`Read`, `Grep`, `Glob`) for agent autonomy.
- Explicit concurrency model (streams, bus, reducer, leases, conflicts).
- Built-in health loop (`diagnose` + `optimize`) for operational reliability.

## Proactive And Autonomous By Design

DiaSync is built to run proactively in agent workflows without step-by-step human
intervention.

- Soft-trigger protocol tells agents when to run memory operations as work evolves.
- Every command auto-initializes `.memory` when needed, reducing operator setup burden.
- `diagnose` opens findings automatically; `optimize --execute` can apply safe fixes.
- `sync stop` automatically releases held leases to prevent stale contention ownership.

In practice: once attached to an agent loop, DiaSync can continuously maintain memory
quality and continuity as part of normal execution.

## Built For Two Kinds Of Complexity

DiaSync explicitly manages both long-horizon and concurrent complexity:

- **Diachronic complexity (over time):** session-to-session continuity through
  `attach`, `checkpoint`, `handoff`, append-only history, and `supersedes` correction chains.
- **Synchronic complexity (at the same time):** multi-instance safety through private streams,
  shared bus reduction, lease ownership, and explicit conflict ledgers.

This is the core reason DiaSync remains stable in long-running, multi-agent projects.

## Autonomous Policy Layer

Beyond commands, DiaSync includes policy references for proactive behavior in progressive
disclosure skill systems:

- `.opencode/skills/diasync-memory/references/PROACTIVE_CADENCE.md`
- `.opencode/skills/diasync-memory/references/MEMORY_DEBT.md`
- `.opencode/skills/diasync-memory/references/COMPLEXITY_RADAR.md`

These guides keep operation soft-policy-driven (not hard orchestration logic) while improving
autonomous memory quality over time.

## Who It Is For

DiaSync is a strong fit when you need:

- agent workflows that span many sessions,
- safe shared memory with multiple active instances,
- transparent file-level memory you can inspect and version,
- governance controls instead of silent state mutation.

## Architecture At A Glance

DiaSync uses one installable skill package and one hidden runtime root:

- Skill package: `.opencode/skills/diasync-memory/`
- Runtime root: `.memory/`

Package contents:

- `SKILL.md`: activation router and lifecycle baseline.
- `scripts/memoryctl.py`: authoritative runtime implementation.
- `references/*.md`: operational protocols.
- `examples/*.md`: runnable demos.

## How It Works

1. **Capture private context** into per-instance streams (`capture`).
2. **Distill durable objects** from streams (`distill`).
3. **Publish shared knowledge** to bus and converge views (`publish` + `reduce`).
4. **Continuously govern health** with findings and plans (`diagnose` + `optimize`).

## Quick Start

Run from repository root:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope project:demo --project demo --instance-id ins-main --summary "Adopt append-only reducer policy" --proposed-type decision --decision-key reducer-policy
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope project:demo --instance-id ins-main
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```

Stop cleanly:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id ins-main --scope project:demo
```

## Command Groups

- **Lifecycle:** `init`, `sync`, `attach`, `checkpoint`, `handoff`
- **Knowledge flow:** `capture`, `distill`, `publish`, `reduce`, `reconcile`
- **Coordination:** `lease`, `agenda`
- **Governance:** `validate`, `diagnose`, `optimize`, `hygiene`, `stats`

Full reference: `docs/MEMORYCTL_CLI_SPEC.md`.

## Runtime Layout

```text
.memory/
  _meta/         # schemas and policy
  streams/       # per-instance event logs
  bus/           # shared publish channel
  views/         # facts, decisions, commitments, attach capsules
  coordination/  # instances, cursors, reducers, leases, conflicts
  projects/      # state, resume, agenda
  governance/    # findings, scorecards, plans, executions
  index/         # query indexes
  archive/       # compressed historical shards
  evidence/      # optional linked artifacts
```

## Frequently Asked Questions

### What problem does DiaSync Memory solve?

It provides durable, inspectable, cross-session memory for AI agents, including safe
coordination when multiple instances work in parallel.

### Does it require a vector database?

No. Recall is filesystem-native and protocol-driven. This keeps retrieval transparent and
easy to audit.

### Is this only for OpenCode?

The packaged skill targets OpenCode-compatible workflows. The runtime model and CLI can also
be used by other agent systems that can run commands and read files.

### Is concurrency handled explicitly?

Yes. Shared contention is handled through leases and conflict ledgers rather than silent
overwrites.

## Documentation Map

- `docs/ARCHITECTURE.md`: system model and architectural contracts.
- `docs/MEMORY_FORMAT_SPEC.md`: storage layout, schemas, and invariants.
- `docs/MEMORYCTL_CLI_SPEC.md`: command-level reference.
- `docs/SOFT_TRIGGER_PROTOCOL.md`: guidance for command timing.
- `docs/REDUCER_RULES.md`: reduction and conflict behavior.
- `docs/LEASE_PROTOCOL.md`: lease ownership and expiry model.
- `docs/DIAGNOSE_RULES.md`: scoring and finding lifecycle.
- `docs/DEVELOPMENT.md`: local workflow and quality gates.
- `docs/EVOLUTION_FRAMEWORK.md`: autonomous skill-driven memory evolution loop.
- `docs/SKILLS_CATALOG.md`: published skill and capability modules.
- `docs/RELEASE_KIT.md`: publishing and release templates.

## Development And Validation

Core checks:

```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```

Useful smoke checks:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py stats
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --dry-run
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --dry-run
```

End-to-end demo:

- `.opencode/skills/diasync-memory/examples/DEMO_COMMANDS.md`
- `.opencode/skills/diasync-memory/examples/AUTONOMOUS_SESSION.md`

## Publishing

To publish only the skill package, distribute:

- `.opencode/skills/diasync-memory/`

Packaging guide: `.opencode/skills/PUBLISHING.md`.

## Related Search Terms

AI agent memory, long-term memory for autonomous agents, multi-agent memory,
append-only memory ledger, filesystem-native memory, conflict-safe agent synchronization,
OpenCode memory skill, memory for engineering, research, operations, and support agents.

## License

This repository is licensed under the terms in `LICENSE`.
