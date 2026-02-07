# Demo Commands

All commands below use a disposable root `.memory_demo`.

## 1) Instance A starts and captures a decision

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --root .memory_demo --instance-id ins-a --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --root .memory_demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --root .memory_demo --scope project:demo --project demo --instance-id ins-a --summary "Adopt lease-protected decision updates" --proposed-type decision --decision-key architecture-write-path --tags memory,decision --salience high --confidence 0.9
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --root .memory_demo --scope project:demo --instance-id ins-a
```

## 2) Instance A publishes shared cognition

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py publish --root .memory_demo --scope project:demo --project demo --instance-id ins-a --summary "Reducer must emit explicit conflict records on decision key collision" --object-type decision --decision-key reducer-collision-policy --tags reduce,conflict --confidence 0.9
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --root .memory_demo --scope project:demo --reindex
```

## 3) Instance B starts, syncs, and diagnoses health

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --root .memory_demo --instance-id ins-b --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --root .memory_demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --root .memory_demo --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --root .memory_demo --max-actions 5
```

## 4) Handoff and stop

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --root .memory_demo --project demo --scope project:demo --instance-id ins-a --now "Reducer flow stable" --next "Run reconcile on any open conflict"
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --root .memory_demo --project demo --scope project:demo --instance-id ins-a --summary "Session complete" --next-actions "Continue optimization"
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --root .memory_demo --instance-id ins-a --scope project:demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --root .memory_demo --instance-id ins-b --scope project:demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --root .memory_demo
```

## 5) Cleanup

```bash
rm -rf .memory_demo
```
