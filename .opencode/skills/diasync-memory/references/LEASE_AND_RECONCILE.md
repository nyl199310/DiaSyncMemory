# Lease and Reconcile

## Acquire lease for contested keys

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease acquire --instance-id ins-main --scope project:demo --key decision:reducer-collision-policy --ttl-seconds 900
```

## Reconcile conflicts with supersedes chain

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reconcile --id dec-20260207123045-ab12cd34 --summary "Replace optimistic rollout with lease-gated rollout" --resolve-conflict cnf-20260207123300-ee11aa22 --review-at 2026-02-14
```

## Release lease

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease release --instance-id ins-main --scope project:demo --key decision:reducer-collision-policy
```

## Guidance

- Never overwrite history in place.
- Use `supersedes` for correction.
