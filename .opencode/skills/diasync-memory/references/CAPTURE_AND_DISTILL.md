# Capture and Distill

## Capture high-value updates

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope project:demo --project demo --instance-id ins-main --summary "Adopt lease-guarded decision updates" --proposed-type decision --decision-key architecture-write-path --tags memory,decision --salience high --confidence 0.88
```

## Distill stream events into view objects

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope project:demo --instance-id ins-main --limit 200
```

## Guidance

- Capture in one concise sentence.
- Use decision keys on contested choices.
- Distill at milestones and before scope switches.
