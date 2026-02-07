---
name: diasync-memory
description: Operate a filesystem-native memory operating system for cross-session continuity, multi-instance synchronization, conflict resolution, and health optimization. Use when work spans sessions, when multiple agent instances run concurrently, or when memory quality must be diagnosed and improved.
compatibility: OpenCode skill. Requires Python 3.10+ and .opencode/skills/diasync-memory/scripts/memoryctl.py.
metadata:
  architecture: diasync-memory-v1
  layer: skills
---

# DiaSync Memory

## Mission

Run the full `.memory` lifecycle autonomously so sessions feel continuous and concurrent instances converge safely.

`diasync-memory` uses a hyphenated name to comply with the Agent Skills naming specification.

## Core Principles

- Write path is deterministic and append-first.
- Read path is filesystem-native (`Read`, `Grep`, `Glob`) for agent autonomy.
- Concurrency is explicit (streams, bus, leases, conflicts).
- Governance is continuous (diagnose and optimize loop).

## Bootstrap

Use any command and let the script auto-initialize `.memory`, or initialize explicitly:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py init --root .memory
```

## Activation Router

- **Session start or resume**: use `references/ATTACH_AND_SYNC.md`
- **During execution updates**: use `references/CAPTURE_AND_DISTILL.md`
- **Cross-instance knowledge sharing**: use `references/PUBLISH_AND_REDUCE.md`
- **Contention on shared decision keys**: use `references/LEASE_AND_RECONCILE.md`
- **Long-session anti-drift**: use `references/CHECKPOINT_AND_HANDOFF.md`
- **Recall before planning/answering**: use `references/RECALL_PROTOCOL.md`
- **Memory health checks and self-improvement**: use `references/GOVERNANCE_LOOP.md`

## Command Path

All tool commands are executed through:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py <command> ...
```

## Runtime Baseline

1. `sync start`
2. `attach`
3. work with `capture` + `distill`
4. `publish` + `reduce` when knowledge should be shared
5. `checkpoint` during long sessions
6. `handoff` before exit
7. `diagnose` and `optimize` continuously
8. `sync stop`
