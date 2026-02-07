# Release Kit

This file provides copy-paste material for publishing `diasync-memory`.

## 1. GitHub Repository Name Suggestions

- `diasync-memory-skill`
- `agent-diasync-memory`
- `diasync-memory-for-opencode`

## 2. GitHub About (Short)

`Production-ready DiaSync memory skill for AI coding agents: cross-session continuity, multi-instance concurrency, conflict-safe writes, and self-diagnosis on a filesystem-native .memory runtime.`

## 3. GitHub About (Long)

`diasync-memory is a single integrated skill package for OpenCode-compatible agents. It provides deterministic append-only memory writes, autonomous filesystem-native recall, explicit multi-instance coordination (streams/bus/reduce/lease/conflict), and built-in governance (diagnose/optimize). Runtime state is fully agent-managed in hidden .memory.`

## 4. Suggested Topics

- `ai-agent`
- `agent-memory`
- `skills`
- `opencode`
- `filesystem`
- `jsonl`
- `multi-agent`
- `concurrency`
- `diasync-memory`

## 5. Initial Release Notes Template

Title:

`v3.1.0 - Single-package diasync-memory with hidden .memory lifecycle`

Body:

```markdown
## Highlights
- Consolidated into one installable skill package: `diasync-memory`
- Moved deterministic runtime tool inside skill package: `scripts/memoryctl.py`
- Switched runtime root to hidden `.memory` with auto-init lifecycle
- Preserved autonomous recall (filesystem-native `Read`/`Grep`/`Glob` protocol)
- Added production governance loop: `diagnose` + `optimize`

## Commands
- `sync`, `attach`, `capture`, `distill`, `publish`, `reduce`
- `lease`, `reconcile`, `checkpoint`, `handoff`, `agenda`
- `hygiene`, `validate`, `diagnose`, `optimize`, `stats`

## Runtime Model
- Private instance streams
- Shared publish bus
- Deterministic view reduction
- Conflict ledger + lease control
- Hidden `.memory` fully agent-managed lifecycle
```

## 6. README Intro Snippet

```markdown
diasync-memory is a production-ready skill package that gives AI coding agents long-horizon memory continuity and safe concurrent multi-instance coordination. It keeps write operations deterministic and auditable while preserving free, filesystem-native recall.
```
