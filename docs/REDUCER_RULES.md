# Reducer Rules (V3.1)

## 1. Purpose

Reducer transforms `bus/` events into `views/` objects with deterministic rules.

## 2. Input Eligibility

- Only `memory.published` events are reduced.
- Each event is reduced at most once (tracked by `reduced_event_ids.jsonl`).

## 3. Mapping Rules

- `payload.object_type=fact` -> `views/facts`
- `payload.object_type=decision` -> `views/decisions`
- `payload.object_type=commitment` -> `views/commitments`

## 4. Decision Key Collision Rule

If an active decision already exists with the same `decision_key` and conflicting summary:

1. Do not auto-overwrite.
2. Emit conflict record to `coordination/conflicts.jsonl`.
3. Require explicit `reconcile` path.

## 5. Commitment Rule

When reducing commitments with project scope:

- mirror as active agenda item in `projects/<id>/agenda.jsonl`.

## 6. Audit Rule

Reducer appends operation evidence to `coordination/reducers.jsonl`.
