# Memory Format Spec (V3.1)

## 1. Scope

This document defines the filesystem model and data contracts used by `memoryctl`.

Runtime root:

- `.memory/` (hidden, auto-initialized)

## 2. Canonical Data Formats

- Structured ledgers: JSONL
- Narrative capsules: Markdown

JSONL is append-first and line-oriented for auditability and partial recovery.

## 3. Runtime Directory Model

```text
.memory/
  _meta/
    spec.json
    policy.json
    event_schema.json
    object_schema.json
  streams/
  bus/
  views/
    facts/
    decisions/
    commitments/
    attach/
  coordination/
  projects/
  governance/
    findings/
    health/
    actions/
  index/
  archive/
  evidence/
```

## 4. Sharding Conventions

- `streams/`: per-scope/per-instance daily shards (`YYYY-MM-DD.jsonl`).
- `bus/`: per-scope daily shards (`YYYY-MM-DD.jsonl`).
- `views/`: per-type/per-scope monthly shards (`YYYY-MM.jsonl`).
- `archive/`: compressed historical `.jsonl.gz` copies.

## 5. Event Contract

Event schema version:

- `diasync-v1-event`

Required event fields:

- `schema_version`
- `event_id`
- `type`
- `scope`
- `instance_id`
- `run_id`
- `actor`
- `ts_wall`
- `lc`
- `causal_refs`
- `visibility`
- `owner`
- `payload`
- `idempotency_key`
- `hash`

Event types currently include:

- `memory.instance.started`
- `memory.instance.heartbeat`
- `memory.instance.stopped`
- `memory.captured`
- `memory.distilled`
- `memory.published`
- `memory.reduced`
- `memory.reconciled`
- `memory.checkpointed`
- `memory.handoff`

## 6. View Object Contract

Object schema version:

- `diasync-v1-object`

Supported types:

- `fact`
- `decision`
- `commitment`

Required object fields:

- `schema_version`
- `id`
- `type`
- `scope`
- `ts`
- `summary`
- `status`
- `horizon`
- `salience`
- `confidence`
- `tags`
- `event_refs`
- `visibility`
- `owner`
- `hash`

Optional object fields:

- `project`
- `source`
- `review_at`
- `due_at`
- `evidence_ref`
- `supersedes`
- `decision_key`
- `why`
- `assumptions`

## 7. Time And Identity Rules

- Timestamps are UTC ISO-8601 with `Z` suffix.
- `review_at` and `due_at` use `YYYY-MM-DD`.
- IDs are generated with typed prefixes (`evt`, `run`, `ins`, `fac`, `dec`, etc.).

## 8. Hash And Integrity Rules

- Every ledger object carrying `hash` must verify against canonical payload hashing.
- Events additionally carry deterministic `idempotency_key`.
- Hash mismatch is a validation error.

## 9. Append-Only And Correction Rules

- Ledgers are append-only.
- Historical records are never rewritten in place.
- Corrections are represented by new records that reference `supersedes`.
- Conflicts are explicit records, not hidden overwrites.

## 10. Operational Ledgers

Key ledger files include:

- `coordination/instances.jsonl`
- `coordination/cursors.jsonl`
- `coordination/leases.jsonl`
- `coordination/conflicts.jsonl`
- `coordination/reducers.jsonl`
- `governance/findings/findings.jsonl`
- `governance/health/scorecards.jsonl`
- `governance/actions/plans.jsonl`
- `governance/actions/executions.jsonl`

## 11. Recall Behavior

Recall is intentionally filesystem-native and protocol-driven.

There is no ranked recall command; agents read and search memory artifacts directly.
