# Attach and Sync

## Start

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
```

## Heartbeat

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync heartbeat --instance-id ins-main --scope project:demo
```

## Stop

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id ins-main --scope project:demo
```
