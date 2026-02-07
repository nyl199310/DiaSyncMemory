# memoryctl CLI Spec (V3.1)

Executable:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py <command> [options]
```

Default root:

- `.memory` (auto-initialized)

## Commands

- `init`
- `sync`
- `attach`
- `capture`
- `distill`
- `publish`
- `reduce`
- `lease`
- `reconcile`
- `checkpoint`
- `handoff`
- `agenda`
- `hygiene`
- `validate`
- `diagnose`
- `optimize`
- `stats`

## Important Note

There is no scripted `recall` command by design.

Recall is handled by `diasync-memory` protocol using filesystem tools.
