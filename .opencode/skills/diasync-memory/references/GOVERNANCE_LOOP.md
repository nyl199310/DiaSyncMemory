# Governance Loop

## Diagnose

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope project:demo --project demo
```

## Optimize (plan only)

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5
```

## Optimize (safe auto execute)

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5 --execute
```

## Hygiene and validation

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py hygiene --reindex
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
```
