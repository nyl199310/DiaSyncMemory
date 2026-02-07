# diasync-memory

Integrated DiaSync memory skill for OpenCode-compatible agents.

## Components

- `SKILL.md`: activation router and runtime baseline
- `scripts/memoryctl.py`: deterministic memory operations
- `references/`: on-demand protocol details
- `examples/`: demo commands and session scripts

## Default Runtime Root

- `.memory/` (auto-initialized)

## Quick Check

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
```
