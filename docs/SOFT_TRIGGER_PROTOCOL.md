# Soft Trigger Protocol (V3.1)

The agent decides when to execute memory operations.

## Trigger Summary

- Session start: `sync start` + `attach`
- During execution changes: `capture`
- Milestones/scope switch: `distill`
- Shareable cross-instance updates: `publish`
- Bus backlog or before planning: `reduce`
- Contested updates: `lease acquire` + `reconcile` + `lease release`
- Long sessions and pre-compression: `checkpoint`
- Session end: `handoff` + `sync stop`
- Health loop: `diagnose` then `optimize`

## Recall Trigger

Use diasync-memory recall protocol before planning and high-impact responses:

1. read attach and project capsules
2. grep views
3. read matched shards
4. load evidence lazily

## Guardrails

- do not rewrite history
- use `supersedes` for correction
- keep capture concise
- keep uncertainty explicit
