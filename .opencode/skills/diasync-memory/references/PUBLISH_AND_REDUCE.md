# Publish and Reduce

## Publish shareable cognition

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py publish --scope project:demo --project demo --instance-id ins-main --summary "Reducer emits explicit conflict records on decision_key collision" --object-type decision --decision-key reducer-collision-policy --tags reduce,conflict --confidence 0.9
```

## Reduce bus events into shared views

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --scope project:demo --limit 500 --reindex
```

## Guidance

- Publish only stable, cross-instance useful knowledge.
- Run reduce before high-impact planning.
