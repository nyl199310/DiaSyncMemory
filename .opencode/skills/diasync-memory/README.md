# diasync-memory

> OpenCode skill for filesystem-native AI agent memory, cross-session continuity, and
> conflict-safe multi-instance synchronization.

`diasync-memory` is a production-oriented skill package that gives AI agents and assistants
durable, inspectable long-term memory using append-only ledgers in `.memory/`.

If you are looking for **agent memory**, **LLM long-term memory**, **assistant memory**,
or **multi-agent memory coordination**, this package is designed for that use case.

## End-State (Begin With The End)

The target state is that an agent can continue work at any time with minimal friction and no
manual memory babysitting, while still being fully auditable.

The agent should reliably recover:

- current goal and stage,
- active decisions and commitments,
- unresolved conflicts and risks,
- and next concrete action.

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

## First-Principles Model

- Concurrency is normal, not exceptional.
- Write correctness is stronger than retrieval convenience.
- History is append-only and corrections are explicit.
- Soft policy beats rigid hard-coded orchestration.
- Autonomous upkeep is preferred over reactive cleanup.

## Handles Both Time And Concurrency Complexity

DiaSync is designed to manage two hard classes of agent-memory complexity:

- **Diachronic complexity (over time):** continuity across long sessions and handoffs.
- **Synchronic complexity (same-time concurrency):** coordination across active instances.

Implemented mechanisms include attach/resume capsules, append-only ledgers, reduction,
lease ownership, and explicit conflict records.

## Autonomous Policy Modules

- `references/PROACTIVE_CADENCE.md`: default proactive operating cadence.
- `references/MEMORY_DEBT.md`: soft debt triage and prioritization.
- `references/COMPLEXITY_RADAR.md`: diachronic/synchronic signal handling.
- `references/GOVERNANCE_LOOP.md`: diagnose/optimize maintenance cycle.

## Package Structure

- `SKILL.md`: activation router and runtime baseline.
- `scripts/memoryctl.py`: authoritative runtime command entrypoint.
- `references/`: protocol-level operating guides.
- `examples/`: runnable demos and session flows.

Key scenarios:

- `examples/DEMO_COMMANDS.md`
- `examples/AUTONOMOUS_SESSION.md`

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

- Long-running tasks that span many sessions.
- Multiple concurrent agent instances sharing one project memory.
- Teams that require auditable, file-level memory traces.
- Workflows where silent overwrite behavior is unacceptable.

## Progressive Disclosure Fit

The skill is designed for discovery/activation/execution workflows:

- Discovery: description encodes when this skill should activate.
- Activation: `SKILL.md` provides strategy and policy layers.
- Execution: references provide scenario-specific command guidance.

## FAQ

### Does this require a vector database?

No. Recall is filesystem-native and protocol-driven.

### Is conflict handling explicit?

Yes. Decision key collisions create conflict records; reconciliation is explicit.

### Is this autonomous or human-driven?

Both are supported, but the design target is proactive autonomous operation with soft
policies and auditable outcomes.

### Can I publish only this skill package?

Yes. See `../PUBLISHING.md` for packaging guidance.

## Related Search Terms

AI agent memory, long-term memory for autonomous agents, OpenCode memory skill, multi-agent
memory synchronization, append-only memory ledger, filesystem-native memory for LLM agents.
