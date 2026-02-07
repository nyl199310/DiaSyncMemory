---
name: diasync-memory
description: Proactively and autonomously operate filesystem-native memory for AI agents and assistants across diachronic (over-time) and synchronic (concurrent) complexity using soft triggers, append-only integrity, conflict-safe coordination, and continuous diagnose/optimize governance.
compatibility: OpenCode skill. Requires Python 3.10+ and .opencode/skills/diasync-memory/scripts/memoryctl.py.
metadata:
  architecture: diasync-memory-v1
  layer: skills
---

# DiaSync Memory

## End State (Begin With The End)

At any moment, the active agent instance should be able to recover and communicate:

- current goal and current stage,
- active decisions and commitments,
- unresolved conflicts and risks,
- and the next concrete action,

while memory remains auditable, convergent, and healthy without step-by-step human intervention.

`diasync-memory` uses a hyphenated name to comply with the Agent Skills naming specification.

## First Principles

- Concurrency is normal, not exceptional.
- Write correctness is stricter than read convenience.
- Autonomy is preferred over manual prompting.
- History is append-only; corrections are explicit (`supersedes`).
- Soft policies guide behavior; avoid rigid hard-coded orchestration.
- Manage both diachronic and synchronic complexity continuously.

## Complexity Model

- **Diachronic complexity (over time):** continuity and drift control across sessions, interruptions, and long-running work.
- **Synchronic complexity (same-time concurrency):** contention and divergence control across multiple active instances.

## Activation Signals (Soft, Not Hard Logic)

High-confidence activation signals:

- user asks to continue prior work, handoff, or "remember context",
- work spans many steps or sessions,
- multiple agents/instances work in parallel,
- quality/risk/governance of memory is requested.

Medium-confidence activation signals:

- major decisions, commitments, or constraints appear,
- planning requires stable shared context,
- unresolved collisions or ambiguity appear.

Low-confidence activation signals:

- brief task with no durable value and no collaboration/concurrency.

## Bootstrap

Use any command and let the script auto-initialize `.memory`, or initialize explicitly:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py init --root .memory
```

## Proactive Baseline Loop

Default autonomous cadence (adapt as needed):

1. `sync start`
2. `attach`
3. recall before planning/answering
4. `capture` during meaningful execution updates
5. `distill` at milestones or scope shifts
6. `publish` + `reduce` for cross-instance knowledge
7. `lease` + `reconcile` for contested keys
8. `diagnose` then `optimize` periodically
9. `checkpoint` during long sessions
10. `handoff` and `sync stop` at session end

## Memory Debt Prioritization

When time is constrained, prioritize by highest observed memory debt:

- convergence debt (published but unreduced, duplicate active decision keys),
- contention debt (unresolved conflicts, stale leases),
- continuity debt (missing attach/checkpoint/handoff freshness),
- governance debt (stale findings, low health trend),
- retrieval debt (stale indexes or poor capsule quality).

Choose actions that reduce the largest debt first.

## Autonomy Guardrails

- Never rewrite historical ledger lines.
- Prefer explicit conflict visibility over silent overwrite.
- Keep uncertainty explicit (`confidence`, assumptions, evidence).
- Use `--dry-run` when safety is unclear.
- Preserve machine-readable outputs and integrity contracts.

## Activation Router

- **Session start or resume**: use `references/ATTACH_AND_SYNC.md`
- **During execution updates**: use `references/CAPTURE_AND_DISTILL.md`
- **Cross-instance knowledge sharing**: use `references/PUBLISH_AND_REDUCE.md`
- **Contention on shared decision keys**: use `references/LEASE_AND_RECONCILE.md`
- **Long-session anti-drift**: use `references/CHECKPOINT_AND_HANDOFF.md`
- **Recall before planning/answering**: use `references/RECALL_PROTOCOL.md`
- **Memory health checks and self-improvement**: use `references/GOVERNANCE_LOOP.md`
- **Autonomous cadence policy**: use `references/PROACTIVE_CADENCE.md`
- **Memory debt triage policy**: use `references/MEMORY_DEBT.md`
- **Diachronic/synchronic radar**: use `references/COMPLEXITY_RADAR.md`

## Command Path

All tool commands are executed through:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py <command> ...
```
