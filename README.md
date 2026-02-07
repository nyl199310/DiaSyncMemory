# DiaSync Memory V3.1

Production-ready, publish-ready memory mechanism for AI coding agents.

This implementation follows first principles:

- deterministic append-only write path
- filesystem-native free retrieval path
- explicit concurrent multi-instance coordination
- continuous diagnosis and optimization

## Package Design

Single integrated skill package:

- `.opencode/skills/diasync-memory/`

Inside the package:

- `SKILL.md` (activation router)
- `scripts/memoryctl.py` (deterministic memory operations)
- `references/*.md` (progressive disclosure details)

Runtime memory root:

- `.memory/` (hidden, agent-managed lifecycle)

## Why This Structure

- One installable skill unit is easier to distribute and version.
- Script colocated with skill avoids path drift.
- Hidden `.memory` keeps runtime state out of normal project surface.

## Quick Start

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
```

`memoryctl` auto-initializes `.memory` on first use.

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/MEMORY_FORMAT_SPEC.md`
- `docs/MEMORYCTL_CLI_SPEC.md`
- `docs/SOFT_TRIGGER_PROTOCOL.md`
- `docs/DEVELOPMENT.md`
- `docs/REDUCER_RULES.md`
- `docs/LEASE_PROTOCOL.md`
- `docs/DIAGNOSE_RULES.md`
- `docs/SKILLS_CATALOG.md`
- `docs/RELEASE_KIT.md`

## Open-Source Publishing

If you want to publish only the skill pack, copy:

- `.opencode/skills/diasync-memory/`

See `.opencode/skills/PUBLISHING.md`.

Demo assets are in `.opencode/skills/diasync-memory/examples/`.
