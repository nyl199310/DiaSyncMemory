# Lease Protocol (V3.1)

## 1. Why Leases

Concurrent instances can race on the same decision key. Leases provide bounded ownership windows for high-contention updates.

## 2. Lease Ledger

File: `coordination/leases.jsonl`

Events:

- `op=acquire`
- `op=release`

## 3. Acquire Rules

1. Keyed by `(scope, key)`.
2. Acquire fails if another instance holds active, non-expired lease.
3. Lease includes `expires_at`.

## 4. Release Rules

1. Holder releases by writing `op=release`.
2. `sync stop` should release all held leases.

## 5. Expiry Rules

- Expired unreleased leases are treated as stale governance issues.
- `optimize --execute` may perform safe stale-lease cleanup.
