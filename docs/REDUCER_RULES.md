# Reducer Rules (V3.1)

## 1. Purpose

The reducer converges shared bus events into normalized view objects.

It is the primary mechanism that turns cross-instance publication into durable, queryable
project memory.

## 2. Input Eligibility

Reducer processes only events that satisfy both rules:

1. Source zone is `bus/`.
2. Event type is `memory.published`.

Any other event type is ignored for reduction.

## 3. Idempotency / At-Most-Once Behavior

- Processed event IDs are tracked in `_meta/reduced_event_ids.jsonl`.
- A previously reduced event is skipped.
- This keeps reduction deterministic across retries.

## 4. Mapping Rules

- `payload.object_type = fact` -> `views/facts/<scope>/<YYYY-MM>.jsonl`
- `payload.object_type = decision` -> `views/decisions/<scope>/<YYYY-MM>.jsonl`
- `payload.object_type = commitment` -> `views/commitments/<scope>/<YYYY-MM>.jsonl`

If `object_type` is invalid, reducer infers a type from summary heuristics.

## 5. Conflict Rule For Decision Keys

When reducing a decision with `decision_key`:

- If an active decision exists in the same scope with the same key and a different summary,
  reducer must open a conflict record.
- Reducer must not overwrite the existing active decision.
- Resolution requires explicit `reconcile` action.

Conflict records are appended to:

- `coordination/conflicts.jsonl`

## 6. Commitment Mirroring Rule

When a reduced object is a `commitment` with a project value:

- mirror the commitment into `projects/<project>/agenda.jsonl` as an active item.

This keeps project queue state synchronized with memory commitments.

## 7. Reducer Audit Trail

Every successful reduction appends operation evidence to:

- `coordination/reducers.jsonl`

Audit rows include event ID, target object ID, scope, type, and timestamp.

## 8. Optional Reindex Behavior

If `reduce` is run with `--reindex`:

- reducer triggers index rebuild (`index/catalog.jsonl`, `index/id_map.jsonl`, etc.).

This is recommended after significant reduction batches.

## 9. Operational Guarantees

- No silent overwrite of contested decisions.
- Visibility of unresolved contention via conflict ledger.
- Deterministic append-only output suitable for replay and auditing.
