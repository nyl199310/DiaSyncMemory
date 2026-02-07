# Architecture (V3.1)

## 1. End-State

An AI memory mechanism that:

- feels continuous across sessions
- handles asynchronous multi-instance concurrency
- keeps write integrity and retrieval flexibility
- continuously diagnoses and optimizes itself

## 2. First-Principles Decisions

1. Concurrency is normal, not exceptional.
2. Write correctness is stronger than read convenience.
3. Read path should preserve agent autonomy.
4. Memory must be auditable and revisable, not mutable in place.
5. Skill activation should remain token-efficient via progressive disclosure.

## 3. Packaging Model

Single integrated skill package:

- `.opencode/skills/diasync-memory/`

Rationale:

- one distributable unit
- one lifecycle contract
- one script/runtime coupling point

## 4. Runtime Memory Substrate

Hidden runtime root:

- `.memory/`

Main zones:

- `streams/` (per-instance private event logs)
- `bus/` (shared publish channel)
- `views/` (facts/decisions/commitments/attach)
- `coordination/` (instances, cursors, leases, conflicts, reducers)
- `projects/` (state/resume/agenda)
- `governance/` (findings, health, optimization plans/executions)
- `index/`, `archive/`, `evidence/`, `_meta/`

## 5. Execution Model

Write path (deterministic):

- `.opencode/skills/diasync-memory/scripts/memoryctl.py`

Read path (autonomous):

- `Read`, `Grep`, `Glob` through the diasync-memory recall protocol

No scripted ranking command for recall.

## 6. Concurrency Contract

- Instances write private streams only.
- Shared knowledge goes through bus.
- Reducer converges bus to views.
- Key collisions become explicit conflicts.
- Leases protect high-contention decision keys.

## 7. Continuity Contract

- `attach`: new-session grounding
- `checkpoint`: long-session anti-drift
- `handoff`: end-session transfer capsule

## 8. Governance Contract

- `diagnose`: score + findings
- `optimize`: plans + safe execution
- `hygiene`: reindex/rotate/archive

This creates a self-improving memory loop.
