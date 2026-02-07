# Diagnose Rules (V3.1)

## 1. Output

`diagnose` returns:

- numeric health score (`0..100`)
- health band (`green|yellow|red`)
- metrics snapshot
- new findings (if any)

## 2. Core Metrics

- stale instances
- open conflict backlog
- stale leases
- reduce lag
- missing attach capsules
- duplicate active decision keys

## 3. Finding Rules

Finding opens only if equivalent `(rule_id, scope, project)` is not already open.

Rule IDs:

- `stale_instance`
- `conflict_backlog`
- `stale_lease`
- `reduce_lag`
- `attach_missing`
- `duplicate_active_decision_key`

## 4. Closing Findings

Findings close via `optimize` executions (safe auto actions) or manual intervention with explicit closure events.
