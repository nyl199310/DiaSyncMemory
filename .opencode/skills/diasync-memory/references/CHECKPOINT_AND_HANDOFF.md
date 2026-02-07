# Checkpoint and Handoff

## In-session checkpoint

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --project demo --scope project:demo --instance-id ins-main --now "Reducer pipeline stable" --next "Run diagnose" --risks "One unresolved conflict" --decisions dec-20260207-aaaa1111 --commitments com-20260207-bbbb2222
```

## End-session handoff

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project demo --scope project:demo --instance-id ins-main --summary "Concurrency memory flow verified" --next-actions "Run optimize" --risks "Open conflict backlog" --open-questions "Lease TTL tuning"
```

## Guidance

- Keep `state.md` and `resume.md` concise and actionable.
- Always provide a concrete first next action.
