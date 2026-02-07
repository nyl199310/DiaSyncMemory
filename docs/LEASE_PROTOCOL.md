# Lease Protocol (V3.1)

## 1. Purpose

Leases serialize high-contention updates (especially decision-key changes) across concurrent
instances without introducing central lock services.

## 2. Ledger Location

Lease events are append-only in:

- `coordination/leases.jsonl`

Supported operations:

- `op=acquire`
- `op=release`

## 3. Lease Key Model

Leases are keyed by tuple:

- `(scope, key)`

Where:

- `scope` is a memory scope (for example `project:demo`)
- `key` is a contention key (for example a decision key)

## 4. Acquire Semantics

Acquire succeeds only when no active, non-expired lease exists for `(scope, key)` owned by
another instance.

Acquire event contains:

- lease identity,
- owner instance,
- acquire timestamp,
- `expires_at` based on TTL,
- content hash for integrity.

## 5. Release Semantics

Release validates ownership when an active lease exists.

Expected behaviors:

- Holder may release explicitly.
- `sync stop` should release all leases held by the stopping instance.

## 6. Expiry And Staleness

Expired unreleased leases are treated as stale governance issues.

Implications:

- `diagnose` reports stale lease findings.
- `optimize --execute` may safely clean stale leases by appending release events.

## 7. Operational Pattern For Contested Updates

Recommended flow:

1. `lease acquire --scope <scope> --key <decision-key> --instance-id <id>`
2. perform update via `reconcile`
3. `lease release --scope <scope> --key <decision-key> --instance-id <id>`

This avoids silent races and provides explicit ownership evidence.

## 8. Failure Modes

- Acquire denied because another owner holds valid lease.
- Release denied because caller is not current owner.
- Expiry timeout leaves stale ledger entry until cleanup.

All outcomes remain auditable through append-only ledger history.

## 9. Design Guarantee

Leases do not hide contention; they structure contention into explicit, time-bounded,
verifiable ownership.
