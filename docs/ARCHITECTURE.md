# Architecture (V3.1)

## 1. System Intent

DiaSync Memory provides durable, auditable memory for AI agents operating across:

- multiple sessions,
- multiple concurrent instances,
- and long-running project timelines.

The architecture prioritizes correctness and recoverability over convenience mutation.

## 2. Design Principles

1. Concurrency is a baseline assumption, not an edge case.
2. Write integrity is stricter than read convenience.
3. Recall remains filesystem-native to preserve agent autonomy.
4. History is append-only; corrections are modeled explicitly.
5. Governance is continuous, not an afterthought.
6. Agent behavior is guided by soft policy, not rigid hard orchestration logic.

## 3. Packaging Model

DiaSync is shipped as a single integrated skill package:

- `.opencode/skills/diasync-memory/`

Rationale:

- One artifact to install, version, and publish.
- One runtime contract for memory lifecycle.
- One authoritative command entrypoint (`memoryctl.py`).

## 4. Runtime Substrate

Runtime state lives in hidden `.memory/` and is auto-initialized.

```text
.memory/
  _meta/         # schemas, policy, runtime metadata
  streams/       # private per-instance event logs
  bus/           # shared publish channel
  views/         # reduced facts/decisions/commitments + attach capsules
  coordination/  # instances, cursors, reducers, conflicts, leases
  projects/      # state.md, resume.md, agenda.jsonl
  governance/    # findings, scorecards, plans, executions
  index/         # catalog and id maps
  archive/       # compressed historical shards
  evidence/      # optional external evidence references
```

## 5. Dataflow Model

### 5.1 Private capture and distillation

1. Agent writes high-value events to `streams/` via `capture`.
2. `distill` transforms captured events into view objects.
3. Distillation records are append-only and hash-verified.

### 5.2 Shared publish and reduction

1. Agent publishes shareable knowledge to `bus/` via `publish`.
2. `reduce` consumes only `memory.published` events.
3. Reduced objects are written to monthly shards in `views/`.
4. Reducer operations are audited in `coordination/reducers.jsonl`.

### 5.3 Continuity artifacts

- `attach` composes startup grounding capsules.
- `checkpoint` writes current-session state.
- `handoff` writes end-session resume context.

## 6. Concurrency And Consistency

DiaSync uses explicit contracts rather than hidden locking:

- **Private write isolation:** instances write to their own stream shards.
- **Shared channel convergence:** bus events are reduced deterministically.
- **Conflict explicitness:** decision-key collisions emit conflict records.
- **Lease control:** `(scope, key)` ownership prevents contested overwrites.

This model keeps races visible and recoverable.

## 7. Governance Loop

Governance is built into runtime operations:

- `diagnose` computes health metrics and opens findings.
- `optimize` generates plans and can execute safe actions.
- `hygiene` reindexes/rotates/archives data for long-term stability.

The loop is intentionally operational: detect, plan, execute, verify.

## 8. Complexity Coverage

DiaSync is explicitly engineered for two complexity classes that break naive agent memory
systems:

- **Diachronic complexity (over time):** context drift across long sessions, interruptions,
  and handoffs.
- **Synchronic complexity (same-time):** contention and divergence across concurrent instances.

Primary controls:

- Diachronic controls: attach capsules, checkpoints, handoff capsules, append-only lineage,
  and `supersedes` correction.
- Synchronic controls: private streams, shared bus reduction, lease ownership, and explicit
  conflict ledgers.

## 9. Recall Model

DiaSync intentionally does not implement a ranked recall command.

Recall is protocol-driven using filesystem tools (`Read`, `Grep`, `Glob`) over:

- attach capsules,
- project state/resume files,
- reduced view shards,
- optional evidence paths.

This keeps retrieval transparent and controllable for agents.

## 10. Non-Goals

The current architecture does not aim to provide:

- vector database retrieval,
- hidden in-place object mutation,
- opaque conflict auto-resolution,
- centralized orchestration service dependencies.

## 11. Architecture In One Sentence

DiaSync Memory is an append-only, filesystem-native, multi-instance memory runtime with
explicit contention handling and continuous self-governance.
