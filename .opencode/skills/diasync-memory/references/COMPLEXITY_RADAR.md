# Complexity Radar

Use this radar to decide whether the current memory challenge is primarily:

- diachronic complexity (over time),
- synchronic complexity (same-time concurrency),
- or a mixed mode.

## 1. Diachronic Complexity (Over Time)

Typical signals:

- frequent context switching,
- long session chains,
- repeated re-discovery of prior decisions,
- drift between current work and prior handoff intent.

Primary controls:

- `attach`
- `checkpoint`
- `handoff`
- concise capture/distill cadence
- explicit superseding correction chains

Starter command pack:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project <project> --scope <scope>
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --project <project> --scope <scope> --instance-id <instance> --now "<state>" --next "<next action>"
```

## 2. Synchronic Complexity (Concurrent)

Typical signals:

- two or more active instances touching related decisions,
- same `decision_key` discussed in parallel,
- conflicting summaries for the same scope.

Primary controls:

- private streams + shared bus/reduce convergence
- lease ownership on contested keys
- explicit conflict ledger + reconcile

Starter command pack:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease acquire --instance-id <instance> --scope <scope> --key <decision-key>
python .opencode/skills/diasync-memory/scripts/memoryctl.py reconcile --id <object-id> --summary "<superseding summary>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease release --instance-id <instance> --scope <scope> --key <decision-key>
```

## 3. Mixed Mode (Most Real Projects)

Many projects combine both complexity classes.

Policy:

- stabilize contention first (synchronic safety),
- then tighten continuity artifacts (diachronic clarity),
- then run governance loop to prevent relapse.

Suggested sequence:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --scope <scope> --reindex
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope <scope> --project <project>
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5
```

## 4. Anti-Patterns

- treating long-horizon drift as only a search problem,
- treating same-time contention as only a narrative disagreement,
- delaying reduction until conflicts become expensive,
- skipping handoff because "state is obvious right now".

## 5. One-Line Heuristic

If the risk is confusion over time, strengthen diachronic controls.
If the risk is collision now, strengthen synchronic controls.
If both are true, resolve collisions first, then refresh continuity.
