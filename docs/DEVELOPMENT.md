# Development Guide (V3.1)

## 1. Primary Artifacts

- `.opencode/skills/diasync-memory/`
- `.memory/` (runtime, hidden)
- `docs/`

## 2. Local Validation

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py --help
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
```

## 3. Typical Flow

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope project:demo --instance-id ins-main --summary "..."
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope project:demo --instance-id ins-main
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project demo --summary "..."
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id ins-main --scope project:demo
```

## 4. Publishing

Publish `.opencode/skills/diasync-memory/` as the skill package.
