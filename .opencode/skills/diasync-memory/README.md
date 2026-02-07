# diasync-memory

> OpenCode skill for filesystem-native AI agent memory, cross-session continuity, and
> conflict-safe multi-instance synchronization.

`diasync-memory` is a production-oriented skill package that gives coding agents durable,
inspectable long-term memory using append-only ledgers in `.memory/`.

If you are looking for **agent memory**, **LLM long-term memory**, **coding assistant memory**,
or **multi-agent memory coordination**, this package is designed for that use case.

## What This Skill Provides

- Deterministic append-only memory writes.
- Filesystem-native recall (no opaque retrieval layer).
- Explicit concurrency controls (bus, reducer, leases, conflicts).
- Continuous governance (`diagnose` and `optimize`).

## Proactive And Autonomous Operation

`diasync-memory` is intended to run proactively inside agent loops, without step-by-step
human intervention.

- Soft triggers define when to run capture/distill/publish/reduce/checkpoint/handoff.
- Commands auto-initialize `.memory` to remove manual bootstrap friction.
- `diagnose` can open findings automatically from runtime conditions.
- `optimize --execute` can apply safe actions automatically.
- `sync stop` releases held leases to keep contention state clean.

## Handles Both Time And Concurrency Complexity

DiaSync is designed to manage two hard classes of agent-memory complexity:

- **Diachronic complexity (over time):** continuity across long sessions and handoffs.
- **Synchronic complexity (same-time concurrency):** coordination across active instances.

Implemented mechanisms include attach/resume capsules, append-only ledgers, reduction,
lease ownership, and explicit conflict records.

## Package Structure

- `SKILL.md`: activation router and runtime baseline.
- `scripts/memoryctl.py`: authoritative runtime command entrypoint.
- `references/`: protocol-level operating guides.
- `examples/`: runnable demos and session flows.

## Runtime Root

- Default: `.memory/`
- Behavior: auto-initialized on first command

## Quick Start

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope project:demo --project demo --instance-id ins-main --summary "Use append-only memory updates"
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope project:demo --instance-id ins-main
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```

Stop the instance:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id ins-main --scope project:demo
```

## Core Command Groups

- Lifecycle: `init`, `sync`, `attach`, `checkpoint`, `handoff`
- Knowledge flow: `capture`, `distill`, `publish`, `reduce`, `reconcile`
- Coordination: `lease`, `agenda`
- Governance: `validate`, `diagnose`, `optimize`, `hygiene`, `stats`

See `references/COMMANDS.md` for a concise command matrix.

## Use Cases

- Long-running coding tasks that span many sessions.
- Multiple concurrent agent instances sharing one project memory.
- Teams that require auditable, file-level memory traces.
- Workflows where silent overwrite behavior is unacceptable.

## FAQ

### Does this require a vector database?

No. Recall is filesystem-native and protocol-driven.

### Is conflict handling explicit?

Yes. Decision key collisions create conflict records; reconciliation is explicit.

### Can I publish only this skill package?

Yes. See `../PUBLISHING.md` for packaging guidance.

## Related Search Terms

AI agent memory, coding agent long-term memory, OpenCode memory skill, multi-agent memory
synchronization, append-only memory ledger, filesystem-native memory for LLM agents.
