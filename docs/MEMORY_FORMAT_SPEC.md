# Memory Format Spec (V3.1)

## 1. Storage Root

- `.memory/` (hidden runtime directory)

The root is created and managed by `memoryctl` automatically.

## 2. Canonical Formats

- Structured: JSONL
- Narrative: Markdown

## 3. Event Schema

Schema version: `diasync-v1-event`

Required fields include:

- `event_id`, `type`, `scope`, `instance_id`, `run_id`
- `ts_wall`, `lc`, `causal_refs`
- `visibility`, `owner`, `payload`
- `idempotency_key`, `hash`

## 4. View Object Schema

Schema version: `diasync-v1-object`

Types:

- `fact`, `decision`, `commitment`

Core fields:

- `id`, `type`, `scope`, `ts`, `summary`
- `status`, `horizon`, `salience`, `confidence`
- `tags`, `event_refs`, `visibility`, `owner`, `hash`

Optional:

- `project`, `decision_key`, `supersedes`, `review_at`, `due_at`, `evidence_ref`, `why`, `assumptions`

## 5. Directory Semantics

- `streams/`: private per-instance daily shards
- `bus/`: shared daily shards
- `views/`: reduced monthly shards
- `coordination/`: lifecycle and contention ledgers
- `governance/`: findings and optimization ledgers

## 6. Integrity Rules

- append-only writes
- no in-place history mutation
- correction through `supersedes`
- content hash verification for every ledger object

## 7. Recall Behavior

Recall is filesystem-native and protocol-driven, not script-ranked.
