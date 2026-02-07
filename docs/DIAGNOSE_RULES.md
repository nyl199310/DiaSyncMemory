# Diagnose Rules (V3.1)

## 1. Purpose

`diagnose` evaluates memory health, produces a score, and opens actionable findings.

It is intended to run regularly as part of operational hygiene.

## 2. Command Output

`diagnose` returns structured JSON containing:

- `score` (`0..100`)
- `health` band (`green|yellow|red`)
- `metrics` snapshot
- `findings_created`

When not in dry-run mode, it also appends scorecards/trends to governance ledgers.

## 3. Measured Metrics

Current metrics include:

- active instances
- stale instances
- open conflicts
- stale leases
- reduce lag (published but not reduced)
- missing attach capsules
- duplicate active decision keys

## 4. Scoring Model

Base score starts at `100`, then penalties are applied:

- stale instances: `min(20, stale_instances * 10)`
- open conflicts: `min(24, open_conflicts * 8)`
- stale leases: `min(16, stale_leases * 8)`
- reduce lag: `min(20, lag_count)`
- missing attach: `min(10, missing_attach * 5)`
- view freshness penalty: `0`, `5`, or `10` depending on reducer recency
- duplicate active decision keys: `min(20, duplicates * 10)`

Band thresholds:

- `green`: `score >= 85`
- `yellow`: `65 <= score < 85`
- `red`: `score < 65`

## 5. Finding Rules

Findings are de-duplicated by tuple:

- `(rule_id, scope, project)`

A new finding opens only if no matching open finding already exists.

Current rule IDs:

- `stale_instance`
- `conflict_backlog`
- `stale_lease`
- `reduce_lag`
- `attach_missing`
- `duplicate_active_decision_key`

## 6. Finding Severity Intent

- High: stale instances, conflict backlog, duplicate decision keys
- Medium: stale leases, reduce lag, missing attach capsules

Severity helps prioritize `optimize` planning order.

## 7. Persistence Behavior

When not `--dry-run`, `diagnose` appends to:

- `governance/health/scorecards.jsonl`
- `governance/health/trends.jsonl`
- `governance/findings/findings.jsonl` (for newly opened findings)

With `--dry-run`, no ledgers are mutated.

## 8. Closing Findings

Findings close through explicit closure events, usually via successful `optimize --execute`
safe actions, or via manual remediation plus closure.

No finding is silently removed from history.

## 9. Operational Recommendation

Run:

1. `diagnose --dry-run` to inspect impact safely,
2. `diagnose` to persist score/finding state,
3. `optimize` (and optionally `--execute`) to address safe issues.
